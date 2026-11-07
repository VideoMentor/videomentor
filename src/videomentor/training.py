"""Training builder: modules of clips, exercises and a quiz.

Pick a tag; get a short module built from your own kept videos: lessons made of
clips (YouTube links with start and end times), an exercise per lesson, a quiz and
gaps. Every clip and quiz answer must sit on a real caption line or chapter; anything
else is dropped. Nothing is downloaded.
"""

from __future__ import annotations

import json
import re
import sqlite3
import threading
from datetime import datetime

from . import db, llm
from .config import library_home
from .library import dumps

MAX_SOURCES = 10
SLACK = 30  # seconds a clip start may sit from a caption line or chapter
MAX_CLIP = 900
WINDOW = 45  # seconds of transcript shown around each moment


class NotEnoughMaterial(Exception):
    """No kept, analyzed videos with this tag yet."""


def _stamp(s: int) -> str:
    h, rem = divmod(int(s), 3600)
    m, sec = divmod(rem, 60)
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m}:{sec:02d}"


def gather(conn: sqlite3.Connection, tag: str, limit: int = MAX_SOURCES) -> list[dict]:
    """Kept, analyzed videos with this tag, strongest signal first, with passages."""
    rows = conn.execute(
        "SELECT i.* FROM items i JOIN item_tags t ON t.item_id = i.id AND t.tag = ?"
        " WHERE i.status = 'kept' AND i.analysis_status = 'done' AND i.analysis IS NOT NULL"
        " ORDER BY COALESCE(json_extract(i.analysis, '$.signal'), 0) DESC, i.analyzed_at DESC"
        " LIMIT ?",
        (tag, limit),
    ).fetchall()
    out = []
    for r in rows:
        item = db.row_to_dict(r)
        a = item["analysis"] if isinstance(item["analysis"], dict) else {}
        tx = conn.execute(
            "SELECT lines FROM transcripts WHERE item_id = ?", (item["id"],)
        ).fetchone()
        lines = [(int(t), text) for t, text in json.loads(tx["lines"])] if tx else []
        chapters = item.get("chapters") or []
        moments = [m for m in (a.get("moments") or []) if isinstance(m.get("t"), int)]
        if isinstance(a.get("key_moment"), dict) and isinstance(a["key_moment"].get("t"), int):
            moments.append(a["key_moment"])
        passages = []
        for m in moments:
            near = [text for t, text in lines if m["t"] - WINDOW <= t <= m["t"] + WINDOW]
            if near:
                passages.append(f"[t={m['t']}s {_stamp(m['t'])}] {' '.join(near)}"[:900])
        out.append(
            {
                "id": item["id"],
                "video_id": item["video_id"],
                "url": item["url"],
                "title": item.get("title"),
                "channel": item.get("channel"),
                "duration_s": item.get("duration_s"),
                "core_idea": a.get("core_idea"),
                "frameworks": a.get("frameworks") or [],
                "takeaways": a.get("takeaways") or a.get("learnings") or [],
                "moments": moments,
                "chapters": chapters,
                "passages": "\n".join(passages),
                "anchors": sorted({t for t, _ in lines} | {int(c["t"]) for c in chapters}),
            }
        )
    return out


SYSTEM = """You are a coach who builds a short, practical training module for one \
person, using only clips from videos they saved and kept. They learn best from short, \
concrete steps.
Return:
- title (under 60 characters) and outcome: what they'll be able to do afterwards.
- minutes: total watch plus practice time.
- lessons: 3 to 5, in a sensible order (basics first). Each has a title, a one-line \
goal, 1 to 4 clips and one concrete exercise they can do this week.
- clips: video (the id given, like yt:abc), start and end in whole seconds, why it's \
in the lesson, and what to watch for. Start each clip at a [t=...s] timestamp shown \
in the passages or a chapter time; clips run 30 seconds to 6 minutes.
- quiz: 5 questions with short answers, each citing the video and the second where \
the answer is (a [t=...s] timestamp).
- gaps: subjects the module needed but these videos don't cover, as short search terms.
Never invent timestamps, videos or claims."""

SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "outcome": {"type": "string"},
        "minutes": {"type": "integer"},
        "lessons": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "goal": {"type": "string"},
                    "clips": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "video": {"type": "string"},
                                "start": {"type": "integer"},
                                "end": {"type": "integer"},
                                "why": {"type": "string"},
                                "watch_for": {"type": "string"},
                            },
                            "required": ["video", "start", "end", "why", "watch_for"],
                        },
                    },
                    "exercise": {"type": "string"},
                },
                "required": ["title", "goal", "clips", "exercise"],
            },
        },
        "quiz": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "question": {"type": "string"},
                    "answer": {"type": "string"},
                    "video": {"type": "string"},
                    "t": {"type": "integer"},
                },
                "required": ["question", "answer", "video", "t"],
            },
        },
        "gaps": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["title", "outcome", "minutes", "lessons", "quiz", "gaps"],
}


def _describe(s: dict) -> str:
    parts = [f"video: {s['id']}", f"title: {s['title']}", f"channel: {s['channel']}"]
    if s.get("duration_s"):
        parts.append(f"length: {_stamp(s['duration_s'])}")
    if s.get("core_idea"):
        parts.append(f"core idea: {s['core_idea']}")
    if s["frameworks"]:
        parts.append(
            "frameworks: " + "; ".join(f"{f.get('name')}: {f.get('how')}" for f in s["frameworks"])
        )
    if s["takeaways"]:
        parts.append("takeaways: " + "; ".join(s["takeaways"][:5]))
    if s["chapters"]:
        parts.append(
            "chapters: " + "; ".join(f"[t={c['t']}s] {c['label']}" for c in s["chapters"][:20])
        )
    if s["passages"]:
        parts.append("passages:\n" + s["passages"])
    return "\n".join(parts)


def _real(t: object, anchors: list[int]) -> bool:
    return isinstance(t, int) and t >= 0 and any(abs(t - a) <= SLACK for a in anchors)


def _link(s: dict, start: int) -> str:
    return f"https://www.youtube.com/watch?v={s['video_id']}&t={int(start)}s"


def validate(raw: dict, sources: list[dict]) -> dict:
    by_id = {s["id"]: s for s in sources}
    dropped = 0
    lessons = []
    for lesson in raw.get("lessons") or []:
        clips = []
        for c in lesson.get("clips") or []:
            s = by_id.get(c.get("video"))
            start, end = c.get("start"), c.get("end")
            ok = (
                s is not None
                and isinstance(end, int)
                and _real(start, s["anchors"])
                and start + 5 < end <= start + MAX_CLIP
                and end <= (s["anchors"][-1] if s["anchors"] else 0) + 60
            )
            if not ok:
                dropped += 1
                continue
            clips.append(
                c
                | {
                    "title": s["title"],
                    "channel": s["channel"],
                    "video_id": s["video_id"],
                    "url": _link(s, start),
                    "embed": f"https://www.youtube.com/embed/{s['video_id']}?start={start}&end={end}",
                    "thumbnail": f"https://i.ytimg.com/vi/{s['video_id']}/hqdefault.jpg",
                }
            )
        lessons.append({**lesson, "clips": clips})
    quiz = []
    for q in raw.get("quiz") or []:
        s = by_id.get(q.get("video"))
        if s is None or not _real(q.get("t"), s["anchors"]):
            dropped += 1
            continue
        quiz.append(q | {"url": _link(s, q["t"]), "title": s["title"]})
    return {
        "title": raw.get("title") or "Training",
        "outcome": raw.get("outcome") or "",
        "minutes": raw.get("minutes"),
        "lessons": lessons,
        "quiz": quiz,
        "gaps": [g for g in raw.get("gaps") or [] if isinstance(g, str)],
        "dropped": dropped,
    }


def build(
    conn: sqlite3.Connection,
    tag: str,
    model: str,
    goal: str | None = None,
    minutes: int | None = None,
) -> dict:
    sources = gather(conn, tag)
    if not sources:
        raise NotEnoughMaterial(tag)
    prompt = f"Subject: {tag}\n"
    if goal:
        prompt += f"Their goal: {goal}\n"
    prompt += f"Time they have: about {minutes or 45} minutes.\n\nVideos:\n\n"
    prompt += "\n\n".join(_describe(s) for s in sources)
    raw = llm.structured(prompt, system=SYSTEM, schema=SCHEMA, model=model, timeout=600)
    module = validate(raw, sources)
    module.update({"tag": tag, "goal": goal, "sources": [s["id"] for s in sources]})
    return module


# --- storage, background runs, export -------------------------------------------


def create(
    conn: sqlite3.Connection, tag: str, goal: str | None = None, minutes: int | None = None
) -> int:
    if not gather(conn, tag, limit=1):
        raise NotEnoughMaterial(tag)
    cur = conn.execute(
        "INSERT INTO training_modules (tag, goal, minutes, status, created_at) VALUES (?, ?, ?, 'building', ?)",
        (tag, goal, minutes, db.now()),
    )
    conn.commit()
    return cur.lastrowid


def run_build(conn: sqlite3.Connection, module_id: int, model: str) -> None:
    row = conn.execute("SELECT * FROM training_modules WHERE id = ?", (module_id,)).fetchone()
    try:
        module = build(conn, row["tag"], model, row["goal"], row["minutes"])
        path = write_markdown(module, module_id)
        conn.execute(
            "UPDATE training_modules SET status = 'ready', title = ?, module = ?, path = ?,"
            " finished_at = ? WHERE id = ?",
            (module["title"], dumps(module), str(path), db.now(), module_id),
        )
    except Exception as e:  # noqa: BLE001 - recorded for the phone to show
        conn.execute(
            "UPDATE training_modules SET status = 'failed', error = ?, finished_at = ? WHERE id = ?",
            (str(e)[:500], db.now(), module_id),
        )
    conn.commit()


def start_thread(fn) -> None:
    threading.Thread(target=fn, name="vm-train", daemon=True).start()


def get(conn: sqlite3.Connection, module_id: int) -> dict | None:
    r = conn.execute("SELECT * FROM training_modules WHERE id = ?", (module_id,)).fetchone()
    if not r:
        return None
    d = dict(r)
    d["module"] = json.loads(d["module"]) if d["module"] else None
    return d


def list_modules(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute("SELECT * FROM training_modules ORDER BY id DESC").fetchall()
    out = []
    for r in rows:
        d = dict(r)
        m = json.loads(d.pop("module")) if d["module"] else None
        d["lessons"] = len(m["lessons"]) if m else 0
        d["clips"] = sum(len(lesson["clips"]) for lesson in m["lessons"]) if m else 0
        out.append(d)
    return out


def render_markdown(m: dict) -> str:
    lines = [f"# {m['title']}", "", f"_{m['outcome']}_", ""]
    meta = [f"Tag: {m.get('tag')}"]
    if m.get("minutes"):
        meta.append(f"about {m['minutes']} minutes")
    if m.get("goal"):
        meta.append(f"goal: {m['goal']}")
    lines += [" · ".join(meta), ""]
    for i, lesson in enumerate(m["lessons"], start=1):
        lines += [f"## Lesson {i}: {lesson['title']}", "", lesson.get("goal", ""), ""]
        for c in lesson["clips"]:
            lines.append(
                f"- [▶ {_stamp(c['start'])}]({c['url']}) (to {_stamp(c['end'])}) **{c['title']}**: "
                f"{c['why']} Watch for: {c['watch_for']}"
            )
        lines += ["", f"**Exercise:** {lesson['exercise']}", ""]
    if m["quiz"]:
        lines += ["## Quiz", ""]
        for i, q in enumerate(m["quiz"], start=1):
            lines.append(
                f"{i}. {q['question']}  \n   Answer: {q['answer']} ([{_stamp(q['t'])}]({q['url']}))"
            )
        lines.append("")
    if m["gaps"]:
        lines += ["## Not covered yet", ""] + [f"- {g}" for g in m["gaps"]] + [""]
    return "\n".join(lines)


def write_markdown(m: dict, module_id: int):
    folder = library_home() / "training"
    folder.mkdir(parents=True, exist_ok=True)
    slug = re.sub(r"[^a-z0-9]+", "-", m["title"].lower()).strip("-")[:50] or "module"
    path = folder / f"{datetime.now():%Y-%m-%d}-{slug}-{module_id}.md"
    path.write_text(render_markdown(m))
    return path
