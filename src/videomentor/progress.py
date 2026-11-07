"""Progress and milestones for celebrations (try/celebrations).

Counted on the server from your own decisions (not undone, not automatic), so the
numbers match on phone and iPad, and each milestone pops up once, on one device.
"""

from __future__ import annotations

import sqlite3
from datetime import date, datetime, timedelta

from . import db

KINDS: dict[str, tuple[list[int], str]] = {
    "videos": ([10, 25, 50, 100, 250, 500, 1000, 2500, 5000], "{n} videos triaged"),
    "hours": ([10, 25, 50, 100, 250, 500, 1000], "{n} hours of video sorted"),
    "streak": ([3, 7, 14, 30, 60, 100, 365], "{n}-day streak"),
}

MINE = (
    "undone = 0 AND action IN ('keep', 'archive', 'prioritize')"
    " AND COALESCE(reason, '') != 'unavailable'"
)


def _local_day(at: str) -> date:
    return datetime.fromisoformat(at).astimezone().date()


def summary(conn: sqlite3.Connection) -> dict:
    ids = [r[0] for r in conn.execute(f"SELECT DISTINCT item_id FROM decisions WHERE {MINE}")]
    marks = ",".join("?" * len(ids)) or "''"
    row = conn.execute(
        f"SELECT COUNT(*) AS n, SUM(status = 'kept') AS kept, SUM(status = 'archived') AS archived,"
        f" COALESCE(SUM(duration_s), 0) AS secs FROM items WHERE id IN ({marks})",
        ids,
    ).fetchone()
    days = [_local_day(r[0]) for r in conn.execute(f"SELECT at FROM decisions WHERE {MINE}")]
    today = datetime.now().astimezone().date()
    seen_days = set(days)
    streak, d = 0, today if today in seen_days else today - timedelta(days=1)
    while d in seen_days:
        streak += 1
        d -= timedelta(days=1)
    return {
        "decided": row["n"],
        "kept": row["kept"] or 0,
        "archived": row["archived"] or 0,
        "hours": round(row["secs"] / 3600, 1),
        "streak_days": streak,
        "today": sum(1 for x in days if x == today),
    }


def _value(s: dict, kind: str) -> float:
    return {"videos": s["decided"], "hours": s["hours"], "streak": s["streak_days"]}[kind]


def seen_ids(conn: sqlite3.Connection) -> set[str]:
    return {r[0] for r in conn.execute("SELECT id FROM milestones_seen")}


def achieved(s: dict) -> list[dict]:
    out = []
    for kind, (steps, label) in KINDS.items():
        for n in steps:
            if _value(s, kind) >= n:
                out.append(
                    {"id": f"{kind}-{n}", "kind": kind, "value": n, "label": label.format(n=n)}
                )
    return out


def unseen(conn: sqlite3.Connection, s: dict | None = None) -> list[dict]:
    """The highest new milestone per kind (lower ones aren't worth a pop-up later)."""
    s = s or summary(conn)
    seen = seen_ids(conn)
    best: dict[str, dict] = {}
    for m in achieved(s):
        best[m["kind"]] = m
    return [m for m in best.values() if m["id"] not in seen]


def mark_seen(conn: sqlite3.Connection, ids: list[str]) -> None:
    """Mark these, and every lower step of the same kind, as shown."""
    ts = db.now()
    for mid in ids:
        kind, _, value = mid.partition("-")
        if kind not in KINDS or not value.isdigit():
            continue
        for n in KINDS[kind][0]:
            if n <= int(value):
                conn.execute(
                    "INSERT OR IGNORE INTO milestones_seen (id, seen_at) VALUES (?, ?)",
                    (f"{kind}-{n}", ts),
                )
    conn.commit()
