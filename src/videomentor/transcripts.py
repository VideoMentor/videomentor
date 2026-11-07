"""Timestamped transcripts, kept after analysis so clips can be cited later.

Raw material for the Training builder: an LLM can point to "4:12 to
7:30" from what was actually said. Captions only; nothing is downloaded but text.
"""

from __future__ import annotations

import json
import logging
import sqlite3

from . import db
from .sources import youtube

log = logging.getLogger(__name__)


def save(conn: sqlite3.Connection, item_id: str, lines: list[tuple[int, str]] | None) -> None:
    """Store captions, or remember that the video has none."""
    conn.execute(
        "INSERT INTO transcripts (item_id, source, lines, fetched_at) VALUES (?, ?, ?, ?)"
        " ON CONFLICT(item_id) DO UPDATE SET source = excluded.source, lines = excluded.lines,"
        " fetched_at = excluded.fetched_at",
        (
            item_id,
            "captions" if lines else "none",
            json.dumps([[int(t), text] for t, text in lines or []], ensure_ascii=False),
            db.now(),
        ),
    )


def get(conn: sqlite3.Connection, item_id: str) -> dict | None:
    row = conn.execute("SELECT * FROM transcripts WHERE item_id = ?", (item_id,)).fetchone()
    if not row:
        return None
    return dict(row) | {"lines": json.loads(row["lines"])}


def fetch_missing(conn: sqlite3.Connection, chrome_profile: str, limit: int = 1000) -> dict:
    """Fetch transcripts for analyzed videos that don't have one stored yet."""
    from . import markdown  # markdown reads transcripts

    rows = conn.execute(
        "SELECT id, video_id FROM items WHERE analysis_status = 'done' AND available = 1"
        " AND id NOT IN (SELECT item_id FROM transcripts) ORDER BY analyzed_at DESC LIMIT ?",
        (limit,),
    ).fetchall()
    out = {"fetched": 0, "no_captions": 0, "failed": 0}
    for r in rows:
        try:
            lines = youtube.fetch_transcript(r["video_id"], chrome_profile)
        except Exception as e:  # noqa: BLE001 - try the rest
            log.warning("transcript for %s failed: %s", r["id"], e)
            out["failed"] += 1
            continue
        save(conn, r["id"], lines)
        conn.commit()
        markdown.write_item(conn, r["id"])
        out["fetched" if lines else "no_captions"] += 1
    return out
