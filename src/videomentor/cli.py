"""``vm`` command line."""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import logging
import os
import plistlib
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

from . import (
    ai,
    analyze,
    auth,
    backup,
    db,
    library,
    markdown,
    playlists,
    prep,
    render,
    scoring,
    sync,
    tag_merge,
    tagging,
    training,
    transcripts,
    usage,
    youtube_api,
)
from .config import library_home, load_settings, new_pair_code, save_settings

LAUNCH_LABEL = "com.videomentor.serve"
LAUNCH_PLIST = Path.home() / "Library/LaunchAgents" / f"{LAUNCH_LABEL}.plist"


def cmd_sync(args, settings) -> None:
    with db.session() as conn:
        summary = sync.run_sync(conn, settings)
        print(json.dumps(summary, indent=2))
        if not args.no_enrich:
            total = 0
            while n := sync.enrich_pending(conn, settings):
                total += n
                print(f"enriched {total}", end="\r", flush=True)
            print(f"enriched {total} items")


def cmd_prep(args, settings) -> None:
    with db.session() as conn:
        if args.retry_failed:
            conn.execute(
                "UPDATE items SET prep_status = 'pending', prep_attempts = 0"
                " WHERE prep_status = 'failed'"
            )
            conn.execute("UPDATE items SET tag_status = 'pending' WHERE tag_status = 'failed'")
            conn.execute(
                "UPDATE items SET signal_status = 'pending' WHERE signal_status = 'failed'"
            )
            conn.commit()
        total = 0
        while batch := prep.pending(conn, settings.prep_batch_size):
            total += prep.prep_batch(conn, batch, settings.prep_model)
            print(f"prepped {total}", flush=True)
            if args.limit and total >= args.limit:
                break
        print(f"prepped {total} items")
        tagged = 0
        while batch := tagging.pending(conn, settings.prep_batch_size):
            tagged += tagging.tag_batch(conn, batch, settings.prep_model)
            print(f"tagged {tagged}", flush=True)
            if args.limit and tagged >= args.limit:
                break
        print(f"tagged {tagged} items")
        scored = 0
        while batch := scoring.pending(conn, settings.prep_batch_size):
            scored += scoring.score_batch(
                conn,
                batch,
                settings.prep_model,
                scoring.rules(settings.signal_areas, settings.signal_guidance),
            )
            print(f"scored {scored}", flush=True)
            if args.limit and scored >= args.limit:
                break
        print(f"scored {scored} items")


def cmd_analyze(args, settings) -> None:
    with db.session() as conn:
        if args.upgrade:
            print(f"re-queued {analyze.queue_upgrades(conn)} older analyses", flush=True)
            conn.commit()
        if args.retry_failed:
            conn.execute(
                "UPDATE items SET analysis_status = 'queued' WHERE analysis_status = 'failed'"
            )
            conn.commit()
        if args.id:
            item = db.get_item(conn, args.id if args.id.startswith("yt:") else f"yt:{args.id}")
            if not item:
                sys.exit(f"no item {args.id}")
            items = [item]
        else:
            items = []
            for _ in range(args.count):
                nxt = analyze.next_item(conn)
                if not nxt:
                    break
                items.append(nxt)
                conn.execute(
                    "UPDATE items SET analysis_status = 'running' WHERE id = ?", (nxt["id"],)
                )
        for item in items:
            print(f"analyzing {item['id']}: {item.get('title')}", flush=True)
            result = analyze.analyze_item(
                conn,
                item,
                chrome_profile=settings.watch_later_profile,
                model=settings.analysis_model,
                skills=settings.skill_map,
                signal_rules=scoring.rules(settings.signal_areas, settings.signal_guidance),
            )
            print(f"  {result['transcript_source']}: {result['summary'][:160]}")


def cmd_youtube_login(args, settings) -> None:
    """Sign in to the YouTube Data API (read-only). Opens Chrome in the Watch Later profile."""

    def open_url(url: str) -> None:
        print("Opening Google sign-in in Chrome", f"({settings.watch_later_profile})...")
        print(f"If nothing opens, paste this into that Chrome profile:\n{url}\n", flush=True)
        try:
            subprocess.run(
                [
                    "open",
                    "-na",
                    "Google Chrome",
                    "--args",
                    f"--profile-directory={settings.watch_later_profile}",
                    url,
                ],
                check=True,
                capture_output=True,
            )
        except (OSError, subprocess.CalledProcessError):
            import webbrowser

            webbrowser.open(url)

    try:
        st = youtube_api.login(open_url)
    except youtube_api.NotSetUp:
        sys.exit("No OAuth client yet. See docs/setup.md.")
    except youtube_api.SignInNeeded as e:
        sys.exit(f"Sign-in didn't finish: {e}")
    print(st["message"])
    print("Fetching playlist dates...", flush=True)
    with db.session() as conn:
        print(json.dumps(playlists.fill_api_dates(conn), indent=2))


def cmd_playlists(args, settings) -> None:
    with db.session() as conn:
        if args.refresh:
            print(json.dumps(playlists.refresh_list(conn, settings, force=True)), flush=True)
        for pid, on in [(i, True) for i in args.enable] + [(i, False) for i in args.disable]:
            match = conn.execute(
                "SELECT id FROM playlists WHERE id = ? OR title = ? COLLATE NOCASE", (pid, pid)
            ).fetchone()
            if not match:
                sys.exit(f"No playlist {pid!r}. Run `vm playlists --refresh` first.")
            playlists.set_enabled(conn, match["id"], on)
            print(f"{'enabled' if on else 'disabled'}: {pid}")
        if args.enable:
            print(json.dumps(playlists.sync_enabled(conn, settings)), flush=True)
        rows = playlists.list_playlists(conn)
        print(f"{'on':3} {'videos':>6} {'updated':10} {'created':10}  title")
        for r in rows:
            created = (r["created_at"] or "")[:10]
            updated = r["modified_date"] or ""
            if len(updated) == 8:
                updated = f"{updated[:4]}-{updated[4:6]}-{updated[6:]}"
            count = r["video_count"] if r["video_count"] is not None else "?"
            print(
                f"{'✓' if r['enabled'] else '':3} {count:>6} {updated:10} {created:10}  {r['title']}"
            )
        print(
            f"\n{len(rows)} playlists, {sum(r['enabled'] for r in rows)} on. "
            f"YouTube API: {youtube_api.state()['message']}"
        )


def cmd_transcripts(args, settings) -> None:
    """Fetch and keep transcripts for analyzed videos that don't have one yet."""
    with db.session() as conn:
        print(json.dumps(transcripts.fetch_missing(conn, settings.watch_later_profile), indent=2))


def cmd_tags(args, settings) -> None:
    """Draft a tag merge list for you to review on the phone (Status > Tidy tags)."""
    with db.session() as conn:
        if args.draft:
            require_ai(conn, settings)
            print("Drafting merges with", settings.analysis_model, "...", flush=True)
            print(f"{tag_merge.draft(conn, settings.analysis_model)} merges proposed")
        merges = [m for m in tag_merge.list_merges(conn) if m["status"] == "proposed"]
        for m in merges:
            print(f"- {m['keep']}  <=  {', '.join(m['fold'])}  ({m['videos']} videos)")
        tags = tagging.vocabulary(conn)
        print(f"\n{len(tags)} tags now; {len(merges)} proposed merges waiting for review.")


def require_ai(conn, settings) -> None:
    """Stop with the plain reason when AI can't run now (off, or over the monthly cap)."""
    ok, reason = ai.allowed(conn, settings)
    if not ok:
        sys.exit(reason)


def cmd_train(args, settings) -> None:
    """Build a training module for a tag (Sonnet) and write it as Markdown."""
    with db.session() as conn:
        require_ai(conn, settings)
        try:
            mid = training.create(conn, args.tag, args.goal, args.minutes)
        except training.NotEnoughMaterial:
            sys.exit(f"No kept, analyzed videos tagged {args.tag!r} yet.")
        print(f"Building from {len(training.gather(conn, args.tag))} videos...", flush=True)
        training.run_build(conn, mid, settings.analysis_model)
        m = training.get(conn, mid)
        if m["status"] != "ready":
            sys.exit(f"Failed: {m['error']}")
        mod = m["module"]
        clips = sum(len(lesson["clips"]) for lesson in mod["lessons"])
        print(
            f"{mod['title']}: {len(mod['lessons'])} lessons, {clips} clips, {len(mod['quiz'])} quiz"
            f" questions ({mod['dropped']} invented timestamps dropped)"
        )
        print(m["path"])


def cmd_render(args, settings) -> None:
    """Render a training module as one narrated video. Personal use only."""
    with db.session() as conn:
        m = training.get(conn, args.module)
    if not m or m["status"] != "ready" or not m.get("module"):
        sys.exit(f"No ready training module {args.module}. List them with the Train tab.")
    if args.max_clips is not None and args.max_clips < 1:
        sys.exit("--max-clips must be 1 or more.")
    try:
        screens = render.parse_screens(args.screen or [])
    except ValueError as e:
        sys.exit(str(e))

    def show(done: int, total: int, seg) -> None:
        label = seg.title or seg.url or seg.kind
        print(f"[{done}/{total}] {seg.kind}: {label[:70]}", flush=True)

    try:
        out = render.render(
            args.module,
            m["module"],
            screens=screens,
            voice=args.voice,
            max_clips=args.max_clips,
            chrome_profile=settings.watch_later_profile,
            progress=show,
        )
    except render.RenderError as e:
        sys.exit(f"Render failed: {e}")
    print(
        f"{out} ({render.status(args.module).get('seconds', 0) // 60} min). Personal use only: not for sharing."
    )


def version_line() -> str:
    """'VideoMentor v0.9.4 · Build 9BA12CD8.001', from the app build the service serves.

    The login service serves ~/VideoMentor/web (copied at install-service); a build
    in the repo that isn't installed yet is reported as well.
    """

    def read(path: Path) -> dict | None:
        try:
            return json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            return None

    installed = read(library_home() / "web" / "build.json")
    repo = read(Path(__file__).resolve().parents[2] / "web" / "dist" / "build.json")
    stamp = installed or repo
    if not stamp:
        return "VideoMentor (no app build found; run npm run build in web/)"
    line = f"VideoMentor v{stamp.get('version', '?')} · Build {stamp.get('build', '?')} (commit {stamp.get('commit', '?')})"
    if installed and repo and repo.get("build") != installed.get("build"):
        line += f"\nRepo has a newer build not yet installed: v{repo.get('version', '?')} · Build {repo.get('build', '?')}"
    return line


def cmd_status(args, settings) -> None:
    with db.session() as conn:
        print(
            json.dumps(
                {"counts": library.counts(conn), "last_sync": sync.last_sync(conn)}, indent=2
            )
        )


def _size(n: int) -> str:
    return f"{n / 1_048_576:.1f} MB" if n >= 1_048_576 else f"{max(n, 1) / 1024:.0f} KB"


def cmd_backup(args, settings) -> None:
    home = library_home()
    if args.list:
        items = backup.listing(home)
        if not items:
            print("No backups yet.")
        for path, size in items:
            print(f"{path}  {_size(size)}")
        return
    if not (home / "library.db").exists():
        sys.exit(f"No library at {home}.")
    try:
        path = backup.make_backup(home)
    except (OSError, sqlite3.Error, RuntimeError) as e:
        sys.exit(f"Backup failed: {e}")
    removed = backup.prune(home)
    print(f"{path}  {_size(path.stat().st_size)}")
    if removed:
        print(f"Removed {removed} older backup file(s).")


def cmd_stats(args, settings) -> None:
    with db.session() as conn:
        print(usage.report(conn))


def cmd_export(args, settings) -> None:
    with db.session() as conn:
        ids = [r["id"] for r in conn.execute("SELECT id FROM items WHERE available = 1")]
        for item_id in ids:
            markdown.write_item(conn, item_id)
    print(f"wrote {len(ids)} files to {library_home() / 'items' / 'youtube'}")


def _tailscale_name() -> str | None:
    exe = shutil.which("tailscale")
    if not exe:
        return None
    try:
        out = subprocess.run([exe, "status", "--json"], capture_output=True, text=True, timeout=10)
        return json.loads(out.stdout)["Self"]["DNSName"].rstrip(".")
    except (subprocess.SubprocessError, KeyError, json.JSONDecodeError):
        return None


def cmd_pair(args, settings) -> None:
    if args.new:
        settings.pair_code = new_pair_code()
        save_settings(settings)
        print("New pairing code saved. Devices already paired stay signed in.")
    name = _tailscale_name()
    print(f"Pairing code: {settings.pair_code}")
    if name:
        print(f"Open on your phone:  https://{name}/pair?code={settings.pair_code}")
    print(
        f"On this Mac:         http://{settings.host}:{settings.port}/pair?code={settings.pair_code}"
    )


def cmd_import_library(args, settings) -> None:
    """Copy a library folder (for example from an older install) into this one."""
    from .importer import import_library

    target = library_home()
    try:
        report = import_library(Path(args.folder), target)
    except ValueError as e:
        sys.exit(str(e))
    except (OSError, sqlite3.Error) as e:
        sys.exit(f"The import stopped and left nothing behind: {e}")
    print(f"Imported into {target}: {report.items} videos, {report.files} files.")
    print(f"Updated {report.rewritten_paths} stored path(s). The original folder is unchanged.")
    if report.leftover_mentions:
        print("Still mentioning the old folder: " + ", ".join(report.leftover_mentions))


def cmd_devices(args, settings) -> None:
    """Paired devices (sign-ins), newest use first; sign one or all of them out."""
    with db.session() as conn:
        if args.sign_out_all:
            print(
                f"Signed out {auth.sign_out_others(conn, None)} device(s). They pair again with vm pair."
            )
            return
        if args.sign_out:
            if not auth.sign_out(conn, args.sign_out):
                sys.exit(f"No device {args.sign_out}. List them with vm devices.")
            print("Signed out.")
            return
        rows = auth.list_sessions(conn)
    if not rows:
        print("No paired devices. Pair one with vm pair.")
    for d in rows:
        print(
            f"{d['id']}  {d['device']:<22} last used {d['last_seen'][:16]}  paired {d['created_at'][:10]}"
        )


def cmd_serve(args, settings) -> None:
    import uvicorn

    from .api import create_app

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    uvicorn.run(
        create_app(settings, run_worker=not args.no_worker),
        host=settings.host,
        port=settings.port,
        proxy_headers=True,
        log_level="info",
    )


def web_dist() -> Path:
    return Path(__file__).resolve().parents[2] / "web" / "dist"


def install_engine() -> None:
    """Install the `vm` tool and copy the web build into the library home.

    macOS privacy protection blocks a background service from reading ~/Documents
    (where the repo lives) without a permission prompt nobody is there to answer, so
    the engine runs an installed copy and serves the app from ~/VideoMentor/web.
    """
    repo = Path(__file__).resolve().parents[2]
    dist = web_dist()
    if not (dist / "index.html").exists():
        sys.exit("Build the app first: (cd web && npm install && npm run build)")
    web_copy = library_home() / "web"
    shutil.rmtree(web_copy, ignore_errors=True)
    shutil.copytree(dist, web_copy)

    uv = shutil.which("uv") or sys.exit("uv is not on PATH")
    subprocess.run([uv, "tool", "install", "--force", "--reinstall", str(repo)], check=True)


def launch_info(settings) -> dict:
    """How to start the engine; the Mac app and the LaunchAgent both use this."""
    home = library_home()
    try:
        build = str(json.loads((home / "web" / "build.json").read_text()).get("build", ""))
    except (OSError, json.JSONDecodeError, AttributeError):
        build = ""
    # launchd starts with a bare PATH; include where claude, node and tailscale live.
    path = ":".join(
        [
            str(Path.home() / ".local/bin"),
            "/opt/homebrew/bin",
            "/usr/local/bin",
            "/usr/bin",
            "/bin",
            "/usr/sbin",
            "/sbin",
        ]
    )
    return {
        "program": str(Path.home() / ".local/bin/vm"),
        "args": ["serve"],
        "env": {
            "PATH": path,
            "VM_HOME": str(home),
            "VM_WEB_DIST": str(home / "web"),
            "PYTHONUNBUFFERED": "1",
        },
        "log": str(home / "logs" / "serve.log"),
        "port": settings.port,
        "host": settings.host,
        "pair_code": settings.pair_code,
        "version": importlib.metadata.version("videomentor"),
        "build": build,
    }


def cmd_install(args, settings) -> None:
    install_engine()
    print("Installed the vm tool and the app copy. Re-run after code or app changes.")


def cmd_launch_info(args, settings) -> None:
    print(json.dumps(launch_info(settings), indent=2))


def cmd_install_service(args, settings) -> None:
    """Install a copy outside ~/Documents and start it at login."""
    install_engine()
    info = launch_info(settings)
    log = Path(info["log"])
    log.parent.mkdir(parents=True, exist_ok=True)
    plist = {
        "Label": LAUNCH_LABEL,
        "ProgramArguments": [info["program"], *info["args"]],
        "RunAtLoad": True,
        "KeepAlive": True,
        "WorkingDirectory": str(library_home()),
        "EnvironmentVariables": info["env"],
        "StandardOutPath": str(log),
        "StandardErrorPath": str(log),
    }
    LAUNCH_PLIST.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["launchctl", "bootout", f"gui/{os.getuid()}", str(LAUNCH_PLIST)], capture_output=True
    )
    LAUNCH_PLIST.write_bytes(plistlib.dumps(plist))
    subprocess.run(["launchctl", "bootstrap", f"gui/{os.getuid()}", str(LAUNCH_PLIST)], check=True)
    print(f"Installed {LAUNCH_PLIST}; logs in {log}")
    print("Re-run this after code or app changes to update the installed copy.")


def cmd_uninstall_service(args, settings) -> None:
    subprocess.run(
        ["launchctl", "bootout", f"gui/{os.getuid()}", str(LAUNCH_PLIST)], capture_output=True
    )
    LAUNCH_PLIST.unlink(missing_ok=True)
    print("Removed the login service.")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="vm", description="VideoMentor library tools")
    parser.add_argument("--version", action="version", version=version_line())
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("sync", help="pull Watch Later and browser bookmarks, then fetch metadata")
    p.add_argument("--no-enrich", action="store_true")
    p.set_defaults(fn=cmd_sync)

    p = sub.add_parser("prep", help="write why-lines, topics, categories and tags for new items")
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--retry-failed", action="store_true")
    p.set_defaults(fn=cmd_prep)

    p = sub.add_parser("analyze", help="run deep analysis on queued items (or one --id)")
    p.add_argument("--id")
    p.add_argument("--count", type=int, default=1)
    p.add_argument("--retry-failed", action="store_true")
    p.add_argument(
        "--upgrade", action="store_true", help="re-queue kept videos analyzed by an older prompt"
    )
    p.set_defaults(fn=cmd_analyze)

    sub.add_parser("status", help="library counts and last sync").set_defaults(fn=cmd_status)
    p = sub.add_parser("backup", help="back up the library now, or --list the backups")
    p.add_argument("--list", action="store_true", help="list backups, newest first")
    p.set_defaults(fn=cmd_backup)

    sub.add_parser("stats", help="LLM calls, tokens and API-equivalent cost by step").set_defaults(
        fn=cmd_stats
    )

    p = sub.add_parser("playlists", help="list playlists; turn syncing on or off")
    p.add_argument("--refresh", action="store_true", help="re-read every playlist's details")
    p.add_argument("--enable", nargs="*", default=[], metavar="ID_OR_TITLE")
    p.add_argument("--disable", nargs="*", default=[], metavar="ID_OR_TITLE")
    p.set_defaults(fn=cmd_playlists)

    sub.add_parser(
        "youtube-login", help="sign in to the YouTube Data API (read-only) for playlist dates"
    ).set_defaults(fn=cmd_youtube_login)
    sub.add_parser("export", help="rewrite every item's Markdown file").set_defaults(fn=cmd_export)
    p = sub.add_parser("train", help="build a training module from kept videos with a tag")
    p.add_argument("tag")
    p.add_argument("--goal")
    p.add_argument("--minutes", type=int)
    p.set_defaults(fn=cmd_train)

    p = sub.add_parser(
        "render", help="render a training module as one narrated video (personal use)"
    )
    p.add_argument("module", type=int, help="training module id")
    p.add_argument(
        "--screen",
        action="append",
        metavar="LESSON=URL[|LINE]",
        help="a web page shown after a lesson's card, e.g. 2=https://docs.anthropic.com|What to notice",
    )
    p.add_argument("--voice", default=render.VOICE, help="macOS voice (say -v '?' lists them)")
    p.add_argument("--max-clips", type=int, help="only the first N clips (for a quick test)")
    p.set_defaults(fn=cmd_render)

    p = sub.add_parser("tags", help="list proposed tag merges; --draft asks the LLM for new ones")
    p.add_argument("--draft", action="store_true")
    p.set_defaults(fn=cmd_tags)
    sub.add_parser(
        "transcripts", help="keep transcripts for analyzed videos that don't have one"
    ).set_defaults(fn=cmd_transcripts)
    p = sub.add_parser("pair", help="show the pairing link for a phone")
    p.add_argument("--new", action="store_true", help="make a new pairing code")
    p.set_defaults(fn=cmd_pair)

    p = sub.add_parser(
        "import-library", help="copy a library folder into this one (keeps the original)"
    )
    p.add_argument("folder", help="the library folder to copy, for example ~/YouTubeMentor")
    p.set_defaults(fn=cmd_import_library, no_settings=True)

    p = sub.add_parser("devices", help="list paired devices; --sign-out ID or --sign-out-all")
    p.add_argument("--sign-out", metavar="ID")
    p.add_argument("--sign-out-all", action="store_true")
    p.set_defaults(fn=cmd_devices)

    p = sub.add_parser("serve", help="run the app server and background worker")
    p.add_argument("--no-worker", action="store_true")
    p.set_defaults(fn=cmd_serve)

    sub.add_parser(
        "install", help="install the vm tool and app copy (no login service)"
    ).set_defaults(fn=cmd_install)
    p = sub.add_parser("launch-info", help="how to start the engine (for the Mac app)")
    p.add_argument("--json", action="store_true", help="print as JSON (the default)")
    p.set_defaults(fn=cmd_launch_info)
    sub.add_parser("install-service", help="start `vm serve` at login (LaunchAgent)").set_defaults(
        fn=cmd_install_service
    )
    sub.add_parser("uninstall-service", help="remove the login service").set_defaults(
        fn=cmd_uninstall_service
    )

    args = parser.parse_args(argv)
    # import-library fills an empty library folder; loading settings first would create
    # config.toml there, so that command runs without them.
    settings = None if getattr(args, "no_settings", False) else load_settings()
    if args.cmd != "serve":
        logging.basicConfig(level=logging.WARNING)
    if settings is not None:
        ai.configure(settings)  # llm.structured reads the backend choice from these
        try:
            usage.install()  # every LLM call this command makes lands in llm_calls
        except Exception as e:  # usage tracking must never stop a command
            print(f"note: usage tracking is off for this run ({e})", file=sys.stderr)
    args.fn(args, settings)


if __name__ == "__main__":
    main()
