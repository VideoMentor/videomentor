"""HTTP API and app hosting. Contract: docs/superpowers/specs/2026-10-25-youtube-swipe-design.md."""

from __future__ import annotations

import logging
import os
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal
from urllib.parse import parse_qs

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import (
    actions,
    ai,
    auth,
    backup,
    channel_pull,
    db,
    insights,
    library,
    llm,
    markdown,
    playlists,
    progress,
    render,
    scoring,
    sync,
    tag_merge,
    training,
    usage,
    youtube_api,
)
from .config import Settings, library_home, load_settings, save_settings
from .worker import Worker

log = logging.getLogger(__name__)


def web_dist() -> Path:
    """The built app: VM_WEB_DIST (set by the login service), else the repo's web/dist."""
    if env := os.environ.get("VM_WEB_DIST"):
        return Path(env)
    return Path(__file__).resolve().parents[2] / "web" / "dist"


COOKIE = "vm_session"


class DecisionIn(BaseModel):
    client_id: str
    item_id: str
    action: Literal["keep", "archive", "prioritize"]
    at: str | None = None


class BatchIn(BaseModel):
    decisions: list[DecisionIn]


class UndoIn(BaseModel):
    decision_id: int | None = None


class DeviceHintIn(BaseModel):
    hint: str = Field(max_length=20)


class GroupIn(BaseModel):
    anchor_item_id: str


class EventIn(BaseModel):
    client_id: str
    item_id: str
    kind: Literal["flip", "open", "info"]
    at: str | None = None


class EventsIn(BaseModel):
    events: list[EventIn]


class PlaylistIn(BaseModel):
    enabled: bool


class MergeApplyIn(BaseModel):
    approve: list[int] = []
    reject: list[int] = []


class SettingsIn(BaseModel):
    signal_areas: list[str]
    signal_guidance: str
    skill_map: list[str]


class SeenIn(BaseModel):
    ids: list[str]


class ActionIn(BaseModel):
    status: Literal["open", "done", "skipped"] | None = None
    note: str | None = None


class AiIn(BaseModel):
    backend: Literal["auto", "claude_code", "api", "off"] | None = None
    cap_usd: float | None = Field(default=None, ge=0, le=ai.MAX_CAP_USD)


CHECK_SCHEMA = {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"]}


class TrainIn(BaseModel):
    tag: str
    goal: str | None = None
    minutes: int | None = None


class PullIn(BaseModel):
    channel_id: str = Field(pattern=r"^UC[A-Za-z0-9_-]{22}$")
    mode: Literal["newest", "oldest", "range"]
    count: int | None = Field(default=None, ge=1, le=200)
    start: str | None = Field(default=None, max_length=10)
    end: str | None = Field(default=None, max_length=10)
    include_shorts: bool = False
    include_lives: bool = False


class GroupDecideIn(BaseModel):
    client_id: str
    action: Literal["keep", "archive"]


def create_app(settings: Settings | None = None, *, run_worker: bool = True) -> FastAPI:
    settings = settings or load_settings()
    worker = Worker(settings) if run_worker else None
    ai.configure(settings)  # llm.structured reads the backend choice from these
    lockout = auth.Lockout()

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        with db.session():
            pass  # create the schema before the first request
        usage.install()  # the worker's and training's LLM calls land in llm_calls
        auth.redact_access_log()
        if worker:
            worker.start()
        yield
        if worker:
            worker.shutdown()

    app = FastAPI(title="VideoMentor", lifespan=lifespan)
    # The offline pack is several MB of JSON; compressed it's about a quarter of that.
    app.add_middleware(GZipMiddleware, minimum_size=2048)

    @app.middleware("http")
    async def no_referrer(request: Request, call_next):
        # Never pass this app's URLs (which can carry a pairing code) on to other sites.
        response = await call_next(request)
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        return response

    def conn() -> Iterator[sqlite3.Connection]:
        with db.session() as c:
            yield c

    def current_code() -> str:
        """The pairing code on disk, so `vm pair --new` takes effect without a restart."""
        settings.pair_code = auth.code_on_disk(settings.pair_code)
        return settings.pair_code

    def authed(request: Request, c: sqlite3.Connection = Depends(conn)) -> None:
        """A paired device's sign-in cookie, or the pairing code as a Bearer token (scripts)."""
        sid = auth.check_session(c, request.cookies.get(COOKIE) or "")
        if sid:
            request.state.session = sid
            return
        header = request.headers.get("authorization", "")
        if header.lower().startswith("bearer "):
            # The pairing code itself: same lockout as /pair, so it can't be used to guess.
            ok = auth.code_matches(header[7:].strip(), current_code())
            if lockout.attempt(ok):
                raise HTTPException(429, "too many wrong codes; try again later")
            if ok:
                request.state.session = None
                return
        raise HTTPException(401, "pair this device first")

    def no_ai(c: sqlite3.Connection) -> bool:
        """True when AI can't run now, so the deck also deals items prep hasn't reached."""
        return not ai.allowed(c, settings)[0]

    def wake_analysis() -> None:
        if worker:
            worker.analyze_now.set()

    @app.get("/pair", include_in_schema=False)
    def pair(request: Request, code: str = ""):
        return _pair(request, code)

    @app.post("/pair", include_in_schema=False)
    async def pair_form(request: Request):
        """The pairing screen posts the typed code, so it stays out of the address bar."""
        # Parsed by hand: a urlencoded form with one field needs no extra library.
        fields = parse_qs((await request.body())[:2048].decode("utf-8", "replace"))
        return await run_in_threadpool(_pair, request, (fields.get("code") or [""])[0])

    def _pair(request: Request, code: str):
        ok = auth.code_matches(code, current_code())
        if wait := lockout.attempt(ok):
            return HTMLResponse(
                f"<h1>Too many wrong codes.</h1><p>Pairing is paused for {max(1, wait // 60)} more"
                " minute(s). Devices already paired keep working.</p>",
                status_code=429,
            )
        if not ok:
            return HTMLResponse("<h1>That pairing code didn't match.</h1>", status_code=401)
        with db.session() as c:
            token = auth.create_session(c, request.headers.get("user-agent"))
        secure = (
            request.headers.get("x-forwarded-proto") == "https" or request.url.scheme == "https"
        )
        resp = RedirectResponse("/", status_code=303)
        resp.set_cookie(
            COOKIE, token, max_age=400 * 86400, httponly=True, samesite="lax", secure=secure
        )
        return resp

    api = Depends(authed)

    @app.get("/api/devices", dependencies=[api])
    def devices(request: Request, c: sqlite3.Connection = Depends(conn)):
        return {
            "devices": auth.list_sessions(c, request.state.session),
            "expire_days": auth.SESSION_DAYS,
        }

    @app.post("/api/devices/me", dependencies=[api])
    def device_hint(request: Request, body: DeviceHintIn, c: sqlite3.Connection = Depends(conn)):
        """The app reports an iPad that its browser presents as a Mac."""
        if not request.state.session:
            raise HTTPException(400, "only a paired device can describe itself")
        return {"ok": auth.set_hint(c, request.state.session, body.hint)}

    @app.delete("/api/devices/{device_id}", dependencies=[api])
    def device_sign_out(device_id: str, c: sqlite3.Connection = Depends(conn)):
        if not auth.sign_out(c, device_id):
            raise HTTPException(404, "no such device")
        return {"ok": True}

    @app.post("/api/devices/sign-out-others", dependencies=[api])
    def devices_sign_out_others(request: Request, c: sqlite3.Connection = Depends(conn)):
        if not request.state.session:
            raise HTTPException(400, "sign out others from a paired device (or use vm devices)")
        return {"signed_out": auth.sign_out_others(c, request.state.session)}

    @app.get("/api/status", dependencies=[api])
    def status(c: sqlite3.Connection = Depends(conn)):
        return {
            "counts": library.counts(c, include_unprepped=no_ai(c)),
            "last_sync": sync.last_sync(c),
            "worker": worker.state if worker else None,
            "ai": ai.status(c, settings),
            "youtube_api": youtube_api.state(),
            "backups": backup.summary(library_home()),
            "playlists_enabled": c.execute(
                "SELECT COUNT(*) FROM playlists WHERE enabled = 1 AND gone = 0"
            ).fetchone()[0],
        }

    @app.get("/api/deck", dependencies=[api])
    def deck(
        deck: Literal["main", "music"] = "main",
        n: int = 10,
        exclude: str = "",
        source: str = "all",
        sort: Literal["default", "posted", "saved"] = "default",
        dir: Literal["asc", "desc"] = "desc",
        start: str | None = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
        c: sqlite3.Connection = Depends(conn),
    ):
        if source not in ("all", "wl", "playlists") and not source.startswith(("pl:", "ch:")):
            raise HTTPException(422, "unknown source")
        ids = [x for x in exclude.split(",") if x]
        cards = library.deck(c, deck, max(1, min(n, 50)), ids, source, sort, dir, start, no_ai(c))
        return {"cards": cards}

    @app.get("/api/items/{item_id}", dependencies=[api])
    def item(item_id: str, c: sqlite3.Connection = Depends(conn)):
        try:
            return library.item_detail(c, item_id)
        except library.NotFound:
            raise HTTPException(404, "no such item") from None

    def _decide(c: sqlite3.Connection, d: DecisionIn) -> dict:
        result = library.decide(c, d.item_id, d.action, d.client_id, d.at)
        markdown.write_item(c, d.item_id)
        return result

    @app.post("/api/decisions", dependencies=[api])
    def decide(body: DecisionIn, c: sqlite3.Connection = Depends(conn)):
        try:
            result = _decide(c, body)
        except library.NotFound:
            raise HTTPException(404, "no such item") from None
        if body.action in ("prioritize", "keep"):
            wake_analysis()
        return result

    @app.post("/api/decisions/batch", dependencies=[api])
    def decide_batch(body: BatchIn, c: sqlite3.Connection = Depends(conn)):
        results = []
        for d in body.decisions:
            try:
                results.append({"client_id": d.client_id, "ok": True} | _decide(c, d))
            except library.NotFound:
                results.append({"client_id": d.client_id, "ok": False, "error": "no such item"})
        wake_analysis()
        return {"results": results}

    @app.post("/api/undo", dependencies=[api])
    def undo(body: UndoIn, c: sqlite3.Connection = Depends(conn)):
        try:
            result = library.undo(c, body.decision_id)
        except library.UndoConflict as e:
            raise HTTPException(409, str(e)) from None
        for it in result["items"]:
            markdown.write_item(c, it["id"])
        return result

    @app.post("/api/groups", dependencies=[api])
    def group(body: GroupIn, c: sqlite3.Connection = Depends(conn)):
        try:
            return library.create_group(c, body.anchor_item_id)
        except library.NotFound:
            raise HTTPException(404, "no such item") from None

    @app.post("/api/groups/{group_id}/decide", dependencies=[api])
    def group_decide(group_id: int, body: GroupDecideIn, c: sqlite3.Connection = Depends(conn)):
        try:
            result = library.decide_group(c, group_id, body.action, body.client_id)
        except library.NotFound:
            raise HTTPException(404, "no such group") from None
        for it in result["items"]:
            markdown.write_item(c, it["id"])
        wake_analysis()
        return result

    @app.get("/api/ready", dependencies=[api])
    def ready(c: sqlite3.Connection = Depends(conn)):
        return {"items": library.ready(c)}

    @app.post("/api/items/{item_id}/seen", dependencies=[api])
    def seen(item_id: str, c: sqlite3.Connection = Depends(conn)):
        library.mark_seen(c, item_id)
        return {"ok": True}

    @app.get("/api/library", dependencies=[api])
    def library_view(
        status: Literal["kept", "archived", "processed", "inbox"] = "kept",
        q: str | None = None,
        c: sqlite3.Connection = Depends(conn),
    ):
        return {"items": library.library_items(c, status, q)}

    @app.post("/api/events", dependencies=[api])
    def events(body: EventsIn, c: sqlite3.Connection = Depends(conn)):
        return {"stored": library.record_events(c, [e.model_dump() for e in body.events])}

    @app.get("/api/tags", dependencies=[api])
    def tags_list(c: sqlite3.Connection = Depends(conn)):
        return {"tags": insights.tags(c)}

    # :path so tags with a slash ("9/11") route; /history and /items end differently.
    @app.get("/api/tags/{tag:path}/items", dependencies=[api])
    def tag_items(
        tag: str,
        status: Literal["kept", "inbox", "archived", "all"] = "kept",
        c: sqlite3.Connection = Depends(conn),
    ):
        return insights.tag_items(c, tag, status)

    @app.get("/api/insights", dependencies=[api])
    def insights_get(c: sqlite3.Connection = Depends(conn)):
        return insights.insights(c, settings.skill_map)

    @app.get("/api/next-up", dependencies=[api])
    def next_up(
        mode: Literal["watch", "apply"] = "watch",
        skill: str | None = Query(default=None, max_length=100),
        c: sqlite3.Connection = Depends(conn),
    ):
        return insights.next_up(c, mode, skill or None)

    @app.get("/api/tags/{tag}/history", dependencies=[api])
    def tag_history(tag: str, c: sqlite3.Connection = Depends(conn)):
        return library.tag_history(c, tag)

    @app.get("/api/channel", dependencies=[api])
    def channel(
        channel_id: str | None = None,
        name: str | None = None,
        c: sqlite3.Connection = Depends(conn),
    ):
        try:
            return library.channel_summary(c, channel_id, name)
        except library.NotFound:
            raise HTTPException(404, "no such channel") from None

    @app.get("/api/playlists", dependencies=[api])
    def playlists_list(c: sqlite3.Connection = Depends(conn)):
        return {"playlists": playlists.list_playlists(c), "youtube_api": youtube_api.state()}

    @app.get("/api/playlists/{playlist_id}", dependencies=[api])
    def playlist_get(playlist_id: str, c: sqlite3.Connection = Depends(conn)):
        try:
            return playlists.playlist_row(c, playlist_id)
        except library.NotFound:
            raise HTTPException(404, "no such playlist") from None

    @app.post("/api/playlists/{playlist_id}", dependencies=[api])
    def playlist_set(playlist_id: str, body: PlaylistIn, c: sqlite3.Connection = Depends(conn)):
        try:
            row = playlists.set_enabled(c, playlist_id, body.enabled)
        except library.NotFound:
            raise HTTPException(404, "no such playlist") from None
        if body.enabled and worker:
            worker.sync_now.set()  # pull its videos now instead of at the next sync
        return row

    @app.get("/api/tag-merges", dependencies=[api])
    def tag_merges(c: sqlite3.Connection = Depends(conn)):
        return {"merges": tag_merge.list_merges(c), "counts": tag_merge.counts(c)}

    @app.post("/api/tag-merges/apply", dependencies=[api])
    def tag_merges_apply(body: MergeApplyIn, c: sqlite3.Connection = Depends(conn)):
        return tag_merge.apply(c, body.approve, body.reject)

    @app.post("/api/tag-merges/{merge_id}/undo", dependencies=[api])
    def tag_merge_undo(merge_id: int, c: sqlite3.Connection = Depends(conn)):
        try:
            return tag_merge.undo(c, merge_id)
        except KeyError:
            raise HTTPException(404, "no such merge") from None

    def _settings_out() -> dict:
        return {
            "signal_areas": settings.signal_areas,
            "signal_guidance": settings.signal_guidance,
            "skill_map": settings.skill_map,
        }

    @app.get("/api/settings", dependencies=[api])
    def settings_get():
        return _settings_out()

    @app.put("/api/settings", dependencies=[api])
    def settings_put(body: SettingsIn):
        def clean(xs: list[str]) -> list[str]:
            out: list[str] = []
            for x in xs:
                x = " ".join(x.split())[:60]
                if x and x.lower() not in {o.lower() for o in out}:
                    out.append(x)
            return out[:20]

        areas, skills = clean(body.signal_areas), clean(body.skill_map)
        guidance = body.signal_guidance.strip()[:1000]
        if not areas or not skills or not guidance:
            raise HTTPException(422, "areas, skills and guidance can't be empty")
        # The worker shares this Settings object, so new rules apply on its next batch.
        settings.signal_areas, settings.signal_guidance, settings.skill_map = (
            areas,
            guidance,
            skills,
        )
        current_code()  # never write an old pairing code back over a new one
        save_settings(settings)
        return _settings_out()

    @app.get("/api/ai", dependencies=[api])
    def ai_get(c: sqlite3.Connection = Depends(conn)):
        return ai.status(c, settings)

    @app.put("/api/ai", dependencies=[api])
    def ai_put(body: AiIn, c: sqlite3.Connection = Depends(conn)):
        # The worker shares this Settings object, so the change applies on its next batch.
        if body.backend is not None:
            settings.ai_backend = body.backend
        if body.cap_usd is not None:
            settings.ai_monthly_cap_usd = float(body.cap_usd)
        current_code()  # never write an old pairing code back over a new one
        save_settings(settings)
        if worker:
            worker.work_now.set()
            worker.analyze_now.set()
        return ai.status(c, settings)

    @app.post("/api/ai/check", dependencies=[api])
    def ai_check(c: sqlite3.Connection = Depends(conn)):
        """One tiny structured call on the current backend, to show the setup works."""
        backend = ai.backend(settings)
        ok, reason = ai.allowed(c, settings)
        if not ok:
            return {"ok": False, "backend": backend, "message": reason}
        try:
            llm.structured(
                'Reply with {"ok": true}.',
                system="You check that structured output works. Answer only with the JSON.",
                schema=CHECK_SCHEMA,
                model="haiku",
                timeout=60,
                step="check",
            )
        except llm.LLMError as e:
            return {"ok": False, "backend": backend, "message": str(e)[:300]}
        label = "Claude Code" if backend == "claude_code" else "the API key"
        return {"ok": True, "backend": backend, "message": f"AI works through {label}"}

    def require_ai(c: sqlite3.Connection) -> None:
        ok, reason = ai.allowed(c, settings)
        if not ok:
            raise HTTPException(409, reason)

    @app.post("/api/signal/rescore", dependencies=[api])
    def signal_rescore(c: sqlite3.Connection = Depends(conn)):
        queued = scoring.requeue(c)
        if worker:
            worker.work_now.set()
        return {"queued": queued}

    @app.get("/api/progress", dependencies=[api])
    def progress_get(c: sqlite3.Connection = Depends(conn)):
        s = progress.summary(c)
        return s | {"unseen": progress.unseen(c, s)}

    @app.post("/api/milestones/seen", dependencies=[api])
    def milestones_seen(body: SeenIn, c: sqlite3.Connection = Depends(conn)):
        progress.mark_seen(c, body.ids)
        return {"ok": True}

    @app.get("/api/actions", dependencies=[api])
    def actions_list(
        status: Literal["open", "done", "skipped", "all"] = "open",
        c: sqlite3.Connection = Depends(conn),
    ):
        actions.collect(c)
        return {"actions": actions.list_actions(c, status), "counts": actions.counts(c)}

    @app.post("/api/actions/{action_id}", dependencies=[api])
    def action_update(action_id: int, body: ActionIn, c: sqlite3.Connection = Depends(conn)):
        try:
            return actions.update(c, action_id, body.status, body.note)
        except KeyError:
            raise HTTPException(404, "no such action") from None

    @app.post("/api/training", dependencies=[api])
    def training_create(body: TrainIn, c: sqlite3.Connection = Depends(conn)):
        require_ai(c)
        try:
            mid = training.create(
                c, body.tag.strip(), (body.goal or "").strip() or None, body.minutes
            )
        except training.NotEnoughMaterial:
            raise HTTPException(422, "no kept, analyzed videos with this tag yet") from None

        def run():
            with db.session() as c2:
                training.run_build(c2, mid, settings.analysis_model)

        training.start_thread(run)
        return {"id": mid, "status": "building"}

    @app.get("/api/training", dependencies=[api])
    def training_list(c: sqlite3.Connection = Depends(conn)):
        return {"modules": training.list_modules(c)}

    @app.get("/api/offline-pack", dependencies=[api])
    def offline_pack(
        cards: int = 100,
        exclude: str = "",
        source: str = "all",
        c: sqlite3.Connection = Depends(conn),
    ):
        """Everything the phone keeps for when it can't reach this Mac: the kept and archived
        library, ready list, actions, training modules, the next cards of each deck, and
        the details (notes) behind every one of those videos."""
        if source not in ("all", "wl", "playlists") and not source.startswith(("pl:", "ch:")):
            raise HTTPException(422, "unknown source")
        n = max(10, min(cards, 200))
        ids = [x for x in exclude.split(",") if x]
        unprepped = no_ai(c)
        decks = {
            d: library.deck(c, d, n, ids, source, include_unprepped=unprepped)
            for d in ("main", "music")
        }
        kept = library.library_items(c, "kept", None)
        archived = library.library_items(c, "archived", None)
        actions.collect(c)
        modules = training.list_modules(c)
        details = {}
        for m in modules:
            full = training.get(c, m["id"])
            if full and full.get("status") == "ready":
                details[str(m["id"])] = full | {"video": render.status(m["id"])}
        items = {}
        for card in [*kept, *decks["main"], *decks["music"]]:
            if card["id"] not in items:
                try:
                    items[card["id"]] = library.item_detail(c, card["id"])
                except library.NotFound:
                    pass
        return {
            "generated_at": db.now(),
            "library": {"kept": kept, "archived": archived},
            "ready": library.ready(c),
            "actions": {
                **{s: actions.list_actions(c, s) for s in ("all", "open", "done", "skipped")},
                "counts": actions.counts(c),
            },
            "training": {"modules": modules, "details": details},
            "items": items,
            "decks": decks,
        }

    @app.get("/api/training/{module_id}", dependencies=[api])
    def training_get(module_id: int, c: sqlite3.Connection = Depends(conn)):
        m = training.get(c, module_id)
        if not m:
            raise HTTPException(404, "no such module")
        return m | {"video": render.status(module_id)}

    @app.post("/api/training/{module_id}/render", dependencies=[api])
    def training_render(module_id: int, c: sqlite3.Connection = Depends(conn)):
        """Start rendering the module as one narrated video; poll GET."""
        m = training.get(c, module_id)
        if not m or m["status"] != "ready" or not m.get("module"):
            raise HTTPException(404, "no ready module")
        if render.is_busy():
            raise HTTPException(
                409, "another training video is rendering; try again when it finishes"
            )
        try:
            render.check_tools()
        except render.RenderError as e:
            raise HTTPException(422, str(e)) from None

        def run() -> None:
            try:
                render.render(module_id, m["module"], chrome_profile=settings.watch_later_profile)
            except render.Busy:
                render.clear_queued(module_id)  # lost a race to another render
            except render.RenderError:
                log.warning("render of module %s failed", module_id)
            except Exception:
                log.exception("render of module %s failed", module_id)

        render.mark_queued(module_id)
        threading.Thread(target=run, name=f"render-{module_id}", daemon=True).start()
        return render.status(module_id)

    @app.get("/api/training/{module_id}/render", dependencies=[api])
    def training_render_status(module_id: int):
        return render.status(module_id)

    @app.get("/api/training/{module_id}/video", dependencies=[api])
    def training_video(module_id: int):
        path = render.video_path(module_id)
        if render.status(module_id).get("state") != "ready" or not path.exists():
            raise HTTPException(404, "no rendered video")
        return FileResponse(
            path,
            media_type="video/mp4",
            filename=f"training-{module_id}.mp4",
            content_disposition_type="inline",
        )

    @app.post("/api/channel/pull", dependencies=[api])
    def channel_pull_run(body: PullIn, c: sqlite3.Connection = Depends(conn)):
        try:
            out = channel_pull.pull(
                c,
                body.channel_id,
                body.mode,
                body.count,
                body.start,
                body.end,
                chrome_profile=settings.watch_later_profile,
                include_shorts=body.include_shorts,
                include_lives=body.include_lives,
            )
        except (ValueError, channel_pull.NeedsSignIn) as e:
            raise HTTPException(422, str(e)) from None
        except youtube_api.SignInNeeded:
            raise HTTPException(422, "YouTube sign-in expired. Run vm youtube-login.") from None
        except channel_pull.Busy as e:
            raise HTTPException(409, str(e)) from None
        except Exception:
            log.exception("channel pull failed")
            raise HTTPException(502, "YouTube didn't answer. Try again in a minute.") from None
        if worker:
            worker.work_now.set()  # fetch details, tag and score the new videos
        return out

    @app.get("/api/channel-pulls", dependencies=[api])
    def channel_pulls(c: sqlite3.Connection = Depends(conn)):
        return {"channels": channel_pull.pulled_channels(c)}

    @app.post("/api/sync", dependencies=[api])
    def sync_now():
        if worker:
            worker.sync_now.set()
        return {"started": bool(worker)}

    dist = web_dist()
    if dist.is_dir():
        app.mount("/", StaticFiles(directory=dist, html=True), name="web")
    else:

        @app.get("/", include_in_schema=False)
        def no_build():
            return HTMLResponse(
                "<p>The app isn't built yet. Run <code>npm run build</code> in web/.</p>"
            )

    return app
