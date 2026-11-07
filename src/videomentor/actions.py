"""Actions (try/actions): every "try this week" step from kept videos' analyses, in one
checklist with done, skipped and a note. Collected from analyses; never lost when a
video is re-analyzed (done steps stay done, new steps are added).
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta

from . import db
from .library import card

STATUSES = ("open", "done", "skipped")


# Videos whose steps are worth a checklist: kept, analyzed, not music, signal 2 or more.
QUALIFIES = (
    "status = 'kept' AND analysis_status = 'done' AND analysis IS NOT NULL"
    " AND COALESCE(category, '') != 'music'"
    " AND COALESCE(json_extract(analysis, '$.signal'), 3) >= 2"
)


def collect(conn: sqlite3.Connection) -> int:
    """Add steps from qualifying videos that aren't in the list yet. Returns how many.

    Open, untouched steps whose video no longer qualifies (archived later, low signal)
    are removed; done, skipped or noted steps always stay.
    """
    conn.execute(
        f"DELETE FROM actions WHERE status = 'open' AND note IS NULL"
        f" AND item_id NOT IN (SELECT id FROM items WHERE {QUALIFIES})"
    )
    added = 0
    rows = conn.execute(
        f"SELECT id, analysis FROM items WHERE {QUALIFIES} ORDER BY analyzed_at"
    ).fetchall()
    for r in rows:
        try:
            steps = json.loads(r["analysis"]).get("try_this_week") or []
        except (json.JSONDecodeError, AttributeError):
            continue
        for pos, text in enumerate(steps):
            if not isinstance(text, str) or not text.strip():
                continue
            added += conn.execute(
                "INSERT OR IGNORE INTO actions (item_id, text, position, status, created_at)"
                " VALUES (?, ?, ?, 'open', ?)",
                (r["id"], text.strip(), pos, db.now()),
            ).rowcount
    conn.commit()
    return added


def _row(conn: sqlite3.Connection, r: sqlite3.Row) -> dict:
    d = dict(r)
    item = db.get_item(conn, d["item_id"])
    d["item"] = card(conn, item) if item else None
    return d


def list_actions(conn: sqlite3.Connection, status: str = "open") -> list[dict]:
    where = "" if status == "all" else "WHERE a.status = ?"
    args = () if status == "all" else (status,)
    order = "a.done_at DESC" if status in ("done", "skipped") else "i.analyzed_at DESC, a.position"
    rows = conn.execute(
        f"SELECT a.* FROM actions a JOIN items i ON i.id = a.item_id {where} ORDER BY {order}, a.id",
        args,
    ).fetchall()
    return [_row(conn, r) for r in rows]


def update(
    conn: sqlite3.Connection, action_id: int, status: str | None = None, note: str | None = None
) -> dict:
    r = conn.execute("SELECT * FROM actions WHERE id = ?", (action_id,)).fetchone()
    if not r:
        raise KeyError(action_id)
    if status is not None:
        if status not in STATUSES:
            raise ValueError(status)
        done_at = db.now() if status in ("done", "skipped") else None
        conn.execute(
            "UPDATE actions SET status = ?, done_at = ? WHERE id = ?", (status, done_at, action_id)
        )
    if note is not None:
        conn.execute(
            "UPDATE actions SET note = ? WHERE id = ?", (note.strip()[:1000] or None, action_id)
        )
    conn.commit()
    return _row(conn, conn.execute("SELECT * FROM actions WHERE id = ?", (action_id,)).fetchone())


def counts(conn: sqlite3.Connection) -> dict:
    by = dict(conn.execute("SELECT status, COUNT(*) FROM actions GROUP BY status").fetchall())
    week_ago = (datetime.now(UTC) - timedelta(days=7)).isoformat(timespec="seconds")
    week = conn.execute(
        "SELECT COUNT(*) FROM actions WHERE status = 'done' AND done_at >= ?", (week_ago,)
    ).fetchone()[0]
    return {s: by.get(s, 0) for s in STATUSES} | {"done_this_week": week}
