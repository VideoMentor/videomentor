"""Pull YouTube videos in from Watch Later and browser bookmarks, then enrich them."""

from __future__ import annotations

import json
import logging
import sqlite3
from concurrent.futures import ThreadPoolExecutor

import yt_dlp

from . import db, library, playlists
from .config import Settings
from .library import dumps
from .sources import browser, youtube

log = logging.getLogger(__name__)

UNAVAILABLE_MARKERS = ("private video", "video unavailable", "has been removed", "deleted video")


def run_sync(conn: sqlite3.Connection, settings: Settings) -> dict:
    run_id = conn.execute("INSERT INTO sync_runs (started_at) VALUES (?)", (db.now(),)).lastrowid
    conn.commit()
    summary: dict = {"watch_later": {}, "bookmarks": {}, "errors": []}
    before_unavailable = library.counts(conn)["unavailable"]

    if youtube.chrome_readable(settings.watch_later_profile):
        try:
            summary["cookies_saved"] = youtube.export_cookies(settings.watch_later_profile)
        except Exception as e:  # noqa: BLE001 - the saved file from last time still works
            summary["errors"].append(f"cookie export: {e}")
    try:
        entries = youtube.fetch_watch_later(settings.watch_later_profile)
        new = sum(
            library.upsert_item(
                conn,
                e.video_id,
                source="youtube:watch_later",
                title=e.title if e.available else None,
                channel=e.channel,
                channel_id=e.channel_id,
                duration_s=e.duration_s,
                wl_position=e.position,
                available=e.available,
            )
            for e in entries
        )
        summary["watch_later"] = {"seen": len(entries), "new": new}
        conn.commit()
    except Exception as e:  # noqa: BLE001 - keep going with the other sources
        log.exception("watch later sync failed")
        summary["errors"].append(f"watch_later: {e}")

    summary["playlists"] = playlists.run(conn, settings)
    summary["errors"] += summary["playlists"].pop("errors", [])

    try:
        summary["bookmarks"] = _sync_bookmarks(conn, settings)
    except browser.BrowserDataBlocked:
        # Expected inside the login service; Terminal runs of `vm sync` cover bookmarks.
        summary["bookmarks"] = {"skipped": "no access to browser data from the background service"}
    except Exception as e:  # noqa: BLE001
        log.exception("bookmark sync failed")
        summary["errors"].append(f"bookmarks: {e}")
    conn.commit()
    summary["unavailable_archived"] = library.counts(conn)["unavailable"] - before_unavailable

    conn.execute(
        "UPDATE sync_runs SET finished_at = ?, summary = ?, error = ? WHERE id = ?",
        (db.now(), dumps(summary), "; ".join(summary["errors"]) or None, run_id),
    )
    conn.commit()
    return summary


def _sync_bookmarks(conn: sqlite3.Connection, settings: Settings) -> dict:
    profiles = settings.bookmark_chrome_profiles
    if profiles == ["*"]:
        profiles = browser.chrome_profiles()
    hits = [h for p in profiles for h in browser.scan_chrome(p)]
    if settings.bookmark_safari:
        hits += list(browser.scan_safari())
    new = 0
    for h in hits:
        new += library.upsert_item(
            conn,
            h.video_id,
            source=h.source,
            source_ref=f"{h.folder}/{h.title}".strip("/"),
            title=h.title or None,
            added_at=h.added_at,
        )
    return {"seen": len(hits), "new": new}


def last_sync(conn: sqlite3.Connection) -> dict | None:
    row = conn.execute(
        "SELECT * FROM sync_runs WHERE finished_at IS NOT NULL ORDER BY id DESC LIMIT 1"
    ).fetchone()
    if not row:
        return None
    return dict(row) | {"summary": json.loads(row["summary"]) if row["summary"] else None}


# 2: exact post time, channel handle and followers, view count.
# 3: collaborators on two-channel videos.
# (0.9.8 fixed owner subscribers on collaborations; only those rows were re-queued.)
ENRICH_VERSION = 3


def enrich_pending(conn: sqlite3.Connection, settings: Settings, limit: int = 30) -> int:
    """Fetch full metadata for up to ``limit`` items, a few at a time.

    New items come first, then items enriched by an older version of this code.
    """
    rows = conn.execute(
        "SELECT id, video_id, title FROM items WHERE available = 1 AND (enrich_status = 'pending'"
        " OR (enrich_status = 'done' AND enrich_version < ?))"
        " ORDER BY enrich_status = 'pending' DESC, added_at DESC LIMIT ?",
        (ENRICH_VERSION, limit),
    ).fetchall()
    if not rows:
        return 0

    def fetch(row: sqlite3.Row) -> tuple[str, dict | None, str | None]:
        try:
            return (
                row["id"],
                youtube.fetch_metadata(row["video_id"], settings.watch_later_profile),
                None,
            )
        except yt_dlp.utils.DownloadError as e:
            return row["id"], None, str(e)

    with ThreadPoolExecutor(max_workers=settings.enrich_concurrency) as pool:
        results = list(pool.map(fetch, rows))

    for item_id, meta, error in results:
        if meta and not (meta.get("title") or "").strip() and not meta.get("channel"):
            # YouTube answers some deleted or private videos with empty metadata, no error.
            library.mark_unavailable(conn, item_id)
        elif meta:
            conn.execute(
                "UPDATE items SET title = COALESCE(?, title), channel = COALESCE(?, channel),"
                " channel_id = COALESCE(?, channel_id), duration_s = COALESCE(?, duration_s),"
                " description = ?, tags = ?, yt_categories = ?, upload_date = ?, chapters = ?,"
                " posted_ts = ?, channel_handle = ?,"
                " channel_followers = COALESCE(?, channel_followers), view_count = ?,"
                " collaborators = ?,"
                " enrich_status = 'done', enrich_version = ?, updated_at = ? WHERE id = ?",
                (
                    meta["title"],
                    meta["channel"],
                    meta["channel_id"],
                    meta["duration_s"],
                    meta["description"],
                    dumps(meta["tags"]),
                    dumps(meta["yt_categories"]),
                    meta["upload_date"],
                    dumps(meta["chapters"]),
                    meta.get("timestamp"),
                    meta.get("channel_handle"),
                    meta.get("channel_followers"),
                    meta.get("view_count"),
                    dumps(meta["collaborators"]) if meta.get("collaborators") else None,
                    ENRICH_VERSION,
                    db.now(),
                    item_id,
                ),
            )
        elif error and any(m in error.lower() for m in UNAVAILABLE_MARKERS):
            library.mark_unavailable(conn, item_id)
        else:
            log.warning("enrich failed for %s: %s", item_id, error)
            # A failed refresh keeps the old metadata; only a first enrich becomes 'failed'.
            conn.execute(
                "UPDATE items SET enrich_status = CASE WHEN enrich_status = 'done' THEN 'done'"
                " ELSE 'failed' END, enrich_version = ? WHERE id = ?",
                (ENRICH_VERSION, item_id),
            )
    conn.commit()
    return len(results)
