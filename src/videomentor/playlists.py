"""Playlists: list them all, sync the ones you turn on.

yt-dlp (with the browser login) is the main path: names, counts, last updated,
and each enabled playlist's videos in stored order. The Data API, when signed in,
adds creation dates and the date each video was added.
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import UTC, datetime, timedelta

from . import db, library, youtube_api
from .config import Settings
from .sources import youtube

log = logging.getLogger(__name__)

# Watch Later is its own source; "Mix" (RD...) playlists can't be read.
SKIP_IDS = {"WL"}
SKIP_PREFIXES = ("RD",)
DETAILS_MAX_AGE = timedelta(hours=24)


def source_key(playlist_id: str) -> str:
    return f"playlist:{playlist_id}"


def _skip(playlist_id: str) -> bool:
    return playlist_id in SKIP_IDS or playlist_id.startswith(SKIP_PREFIXES)


def refresh_list(conn: sqlite3.Connection, settings: Settings, force: bool = False) -> dict:
    """Update the list of playlists; refresh details older than a day (or all if force)."""
    feed = [
        (pid, title) for pid, title in youtube.fetch_playlist_feed(settings.watch_later_profile)
    ]
    ts = db.now()
    seen = set()
    for order, (pid, title) in enumerate(feed, start=1):
        if _skip(pid):
            continue
        seen.add(pid)
        conn.execute(
            "INSERT INTO playlists (id, title, feed_order, first_seen) VALUES (?, ?, ?, ?)"
            " ON CONFLICT(id) DO UPDATE SET title = COALESCE(excluded.title, title),"
            " feed_order = excluded.feed_order, gone = 0",
            (pid, title, order, ts),
        )
    if seen:
        marks = ",".join("?" * len(seen))
        conn.execute(f"UPDATE playlists SET gone = 1 WHERE id NOT IN ({marks})", tuple(seen))
    conn.commit()

    cutoff = (datetime.now(UTC) - DETAILS_MAX_AGE).isoformat(timespec="seconds")
    stale = [
        r["id"]
        for r in conn.execute(
            "SELECT id FROM playlists WHERE gone = 0"
            " AND (? OR details_at IS NULL OR details_at < ? OR error IS NOT NULL)",
            (int(force), cutoff),
        )
    ]

    def fetch(pid: str) -> tuple[str, dict | None, str | None]:
        try:
            return pid, youtube.fetch_playlist_details(pid, settings.watch_later_profile), None
        except Exception as e:  # noqa: BLE001 - one bad playlist shouldn't stop the rest
            return pid, None, str(e)[:200]

    # One at a time: parallel reads of Chrome's login drop it, and private
    # playlists then look like they don't exist.
    for pid, details, error in map(fetch, stale):
        if details:
            _store_details(conn, pid, details)
        else:
            conn.execute(
                "UPDATE playlists SET error = ?, details_at = ? WHERE id = ?",
                (error, db.now(), pid),
            )
    conn.commit()
    return {"listed": len(seen), "details_refreshed": len(stale)}


def _store_details(conn: sqlite3.Connection, pid: str, d: dict) -> None:
    conn.execute(
        "UPDATE playlists SET title = COALESCE(?, title), video_count = ?, modified_date = ?,"
        " owner = ?, owner_channel_id = ?, visibility = ?, error = NULL, details_at = ?"
        " WHERE id = ?",
        (
            d.get("title"),
            d.get("video_count"),
            d.get("modified_date"),
            d.get("owner"),
            d.get("owner_channel_id"),
            d.get("visibility"),
            db.now(),
            pid,
        ),
    )


def set_enabled(conn: sqlite3.Connection, playlist_id: str, enabled: bool) -> dict:
    cur = conn.execute("UPDATE playlists SET enabled = ? WHERE id = ?", (int(enabled), playlist_id))
    if not cur.rowcount:
        raise library.NotFound(playlist_id)
    conn.commit()
    return playlist_row(conn, playlist_id)


def sync_enabled(conn: sqlite3.Connection, settings: Settings) -> dict:
    """Pull every enabled playlist's videos in stored order."""
    rows = conn.execute("SELECT id, title FROM playlists WHERE enabled = 1 AND gone = 0").fetchall()
    summary = {"playlists": len(rows), "seen": 0, "new": 0, "errors": []}
    for row in rows:
        pid = row["id"]
        try:
            details, entries = youtube.fetch_playlist(pid, settings.watch_later_profile)
        except Exception as e:  # noqa: BLE001
            log.warning("playlist %s failed: %s", pid, e)
            summary["errors"].append(f"{row['title'] or pid}: {str(e)[:120]}")
            continue
        _store_details(conn, pid, details)
        ts = db.now()
        present = []
        for e in entries:
            summary["new"] += library.upsert_item(
                conn,
                e.video_id,
                source=source_key(pid),
                source_ref=details.get("title") or row["title"],
                title=e.title if e.available else None,
                channel=e.channel,
                channel_id=e.channel_id,
                duration_s=e.duration_s,
                available=e.available,
            )
            item_id = f"yt:{e.video_id}"
            present.append(item_id)
            conn.execute(
                "INSERT INTO playlist_items (playlist_id, item_id, position, first_seen)"
                " VALUES (?, ?, ?, ?) ON CONFLICT(playlist_id, item_id)"
                " DO UPDATE SET position = excluded.position",
                (pid, item_id, e.position, ts),
            )
        if present:
            marks = ",".join("?" * len(present))
            # Videos removed from the playlist on YouTube: forget the link, keep the video.
            conn.execute(
                f"DELETE FROM playlist_items WHERE playlist_id = ? AND item_id NOT IN ({marks})",
                (pid, *present),
            )
            conn.execute(
                f"DELETE FROM item_sources WHERE source = ? AND item_id NOT IN ({marks})",
                (source_key(pid), *present),
            )
        conn.execute("UPDATE playlists SET items_synced_at = ? WHERE id = ?", (ts, pid))
        summary["seen"] += len(entries)
        conn.commit()
    return summary


def fill_api_dates(conn: sqlite3.Connection) -> dict:
    """Creation dates for all playlists, save dates for enabled ones. Needs sign-in."""
    st = youtube_api.state()
    if st["state"] != "ok":
        return {"skipped": st["state"]}
    ids = [r["id"] for r in conn.execute("SELECT id FROM playlists WHERE gone = 0")]
    meta = youtube_api.playlists_meta(ids)
    for pid, m in meta.items():
        conn.execute(
            "UPDATE playlists SET created_at = ?, video_count = COALESCE(?, video_count)"
            " WHERE id = ?",
            (m.get("created_at"), m.get("item_count"), pid),
        )
    conn.commit()
    dated, errors = 0, []
    for row in conn.execute(
        "SELECT id, title FROM playlists WHERE enabled = 1 AND gone = 0"
    ).fetchall():
        try:
            dates = youtube_api.playlist_added_dates(row["id"])
        except youtube_api.ApiError as e:
            errors.append(f"{row['title'] or row['id']}: {e}")
            continue
        for vid, added in dates.items():
            dated += conn.execute(
                "UPDATE playlist_items SET added_at = ? WHERE playlist_id = ? AND item_id = ?",
                (added, row["id"], f"yt:{vid}"),
            ).rowcount
        conn.execute("UPDATE playlists SET dates_at = ? WHERE id = ?", (db.now(), row["id"]))
        conn.commit()
    return {"created_dates": len(meta), "save_dates": dated, "errors": errors}


def run(conn: sqlite3.Connection, settings: Settings) -> dict:
    """The playlists part of a sync. Each step keeps going if another fails."""
    out: dict = {"errors": []}
    try:
        out["list"] = refresh_list(conn, settings)
    except Exception as e:  # noqa: BLE001
        log.exception("playlist list failed")
        out["errors"].append(f"playlist list: {e}")
    try:
        synced = sync_enabled(conn, settings)
        out["errors"] += synced.pop("errors")
        out["items"] = synced
    except Exception as e:  # noqa: BLE001
        log.exception("playlist sync failed")
        out["errors"].append(f"playlist items: {e}")
    try:
        api = fill_api_dates(conn)
        out["errors"] += api.pop("errors", [])
        out["api"] = api
    except youtube_api.SignInNeeded:
        out["api"] = {"skipped": "expired"}
    except (youtube_api.NotSetUp, youtube_api.ApiError) as e:
        out["errors"].append(f"youtube api: {e}")
    return out


# --- views -------------------------------------------------------------------

ROW_SQL = """
SELECT p.*,
  (SELECT COUNT(*) FROM playlist_items pi WHERE pi.playlist_id = p.id) AS synced,
  (SELECT MAX(COALESCE(pi.added_at, pi.first_seen)) FROM playlist_items pi
    WHERE pi.playlist_id = p.id) AS newest_save,
  (SELECT MAX(pi.added_at) IS NOT NULL FROM playlist_items pi
    WHERE pi.playlist_id = p.id) AS dates_known,
  (SELECT COUNT(*) FROM playlist_items pi JOIN items i ON i.id = pi.item_id
    WHERE pi.playlist_id = p.id AND i.status = 'inbox' AND i.available = 1) AS inbox,
  (SELECT COUNT(*) FROM playlist_items pi JOIN items i ON i.id = pi.item_id
    WHERE pi.playlist_id = p.id AND i.status = 'kept') AS kept,
  (SELECT COUNT(*) FROM playlist_items pi JOIN items i ON i.id = pi.item_id
    WHERE pi.playlist_id = p.id AND i.status = 'archived') AS archived
FROM playlists p
"""


def _row(r: sqlite3.Row) -> dict:
    d = dict(r)
    d["enabled"] = bool(d["enabled"])
    d["gone"] = bool(d["gone"])
    d["dates_known"] = bool(d["dates_known"])
    if not d["synced"]:
        d["newest_save"] = None
    return d


def list_playlists(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(ROW_SQL + " WHERE p.gone = 0 ORDER BY p.feed_order")
    return [_row(r) for r in rows]


def playlist_row(conn: sqlite3.Connection, playlist_id: str) -> dict:
    r = conn.execute(ROW_SQL + " WHERE p.id = ?", (playlist_id,)).fetchone()
    if not r:
        raise library.NotFound(playlist_id)
    return _row(r)
