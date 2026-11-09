"""Tags, reports and "next up": read-only views over the library.

Endpoints: GET /api/tags, /api/tags/{tag}/items, /api/insights, /api/next-up.
Everything here only reads.
"""

from __future__ import annotations

import json
import sqlite3
import statistics
from datetime import UTC, datetime, timedelta

from . import actions, db, usage
from .library import MAIN_CATEGORIES, card, pulled_only_sql

# Durations over a day are bad metadata (live streams that never ended), so they count as unknown.
DUR = "(CASE WHEN {c}duration_s > 86400 THEN NULL ELSE {c}duration_s END)"
# The analysis as JSON, or an empty object when it's missing or broken (json_* would raise).
ANALYSIS = "(CASE WHEN json_valid({c}analysis) THEN {c}analysis ELSE '{{}}' END)"
DECIDED = ("keep", "prioritize", "archive")


def _dur(alias: str = "") -> str:
    return DUR.format(c=f"{alias}." if alias else "")


def _analysis(alias: str = "") -> str:
    return ANALYSIS.format(c=f"{alias}." if alias else "")


def _minutes(seconds: float | None) -> int:
    return round((seconds or 0) / 60)


def _avg(x: float | None) -> float | None:
    return round(x, 2) if x is not None else None


def _rate(kept: int, archived: int) -> float | None:
    return round(kept / (kept + archived), 3) if kept + archived else None


# --- tags --------------------------------------------------------------------


def tags(conn: sqlite3.Connection) -> list[dict]:
    """Every tag with its counts. item_tags.tag is NOCASE, so grouping ignores case."""
    rows = conn.execute(
        "SELECT t.tag AS tag, COUNT(*) AS total,"
        " SUM(i.status = 'kept') AS kept, SUM(i.status = 'inbox') AS inbox,"
        " SUM(i.status = 'archived') AS archived,"
        " SUM(i.analysis_status = 'done') AS analyzed, AVG(i.signal) AS avg_signal,"
        f" SUM(CASE WHEN i.status = 'kept' THEN {_dur('i')} END) AS seconds"
        " FROM item_tags t JOIN items i ON i.id = t.item_id"
        " GROUP BY t.tag ORDER BY kept DESC, total DESC, t.tag"
    )
    return [
        {
            "tag": r["tag"],
            "total": r["total"],
            "kept": r["kept"],
            "inbox": r["inbox"],
            "archived": r["archived"],
            "analyzed": r["analyzed"],
            "avg_signal": _avg(r["avg_signal"]),
            "minutes": _minutes(r["seconds"]),
        }
        for r in rows
    ]


def _words(conn: sqlite3.Connection, ids: list[str]) -> dict[str, int]:
    """Transcript word counts, for items that have captions."""
    if not ids:
        return {}
    marks = ",".join("?" * len(ids))
    out = {}
    for r in conn.execute(
        f"SELECT item_id, lines FROM transcripts WHERE item_id IN ({marks}) AND source != 'none'",
        ids,
    ):
        try:
            lines = json.loads(r["lines"])
        except json.JSONDecodeError:
            continue
        out[r["item_id"]] = sum(
            len(str(line[1]).split()) for line in lines if isinstance(line, list) and len(line) > 1
        )
    return out


# Caps response size and keeps _words' IN (...) under SQLite's variable limit.
TAG_ITEMS_LIMIT = 500


def tag_items(conn: sqlite3.Connection, tag: str, status: str = "kept") -> dict:
    where, args = ("", ()) if status == "all" else (" AND i.status = ?", (status,))
    a = _analysis("i")
    rows = conn.execute(
        "SELECT t.tag AS tag_name, i.id, i.title, i.channel, i.status, i.signal,"
        f" {_dur('i')} AS duration_s, i.added_at, i.analyzed_at, i.analysis_status,"
        f" COALESCE(json_array_length({a}, '$.key_points'), 0)"
        f" + COALESCE(json_array_length({a}, '$.frameworks'), 0)"
        f" + COALESCE(json_array_length({a}, '$.takeaways'), 0) AS notes,"
        " (SELECT COUNT(*) FROM actions x WHERE x.item_id = i.id AND x.status = 'open')"
        " AS actions_open,"
        " (SELECT COUNT(*) FROM actions x WHERE x.item_id = i.id AND x.status = 'done')"
        " AS actions_done"
        f" FROM item_tags t JOIN items i ON i.id = t.item_id WHERE t.tag = ?{where}"
        " ORDER BY i.signal IS NULL, i.signal DESC, i.added_at DESC LIMIT ?",
        (tag, *args, TAG_ITEMS_LIMIT),
    ).fetchall()
    words = _words(conn, [r["id"] for r in rows])
    items = [
        {
            "id": r["id"],
            "title": r["title"] or "(untitled)",
            "channel": r["channel"],
            "status": r["status"],
            "signal": r["signal"],
            "duration_s": r["duration_s"],
            "words": words.get(r["id"]),
            "notes": r["notes"],
            "actions_open": r["actions_open"],
            "actions_done": r["actions_done"],
            "added_at": r["added_at"],
            "analyzed_at": r["analyzed_at"],
        }
        for r in rows
    ]
    return {
        "tag": rows[0]["tag_name"] if rows else tag,
        "summary": {
            "count": len(rows),
            "minutes": _minutes(sum(r["duration_s"] or 0 for r in rows)),
            "analyzed": sum(r["analysis_status"] == "done" for r in rows),
        },
        "items": items,
    }


# --- insights ----------------------------------------------------------------


def _skills(conn: sqlite3.Connection, skill_map: list[str]) -> list[dict]:
    rows = conn.execute(
        "WITH s AS (SELECT DISTINCT i.id, i.status, i.signal, "
        f"{_dur('i')} AS dur, j.value AS skill"
        f" FROM items i, json_each({_analysis('i')}, '$.skills') j"
        " WHERE i.analysis_status = 'done' AND j.type = 'text')"
        " SELECT skill, SUM(status = 'kept') AS kept, COUNT(*) AS analyzed,"
        " AVG(CASE WHEN status = 'kept' THEN signal END) AS avg_signal,"
        " SUM(CASE WHEN status = 'kept' THEN dur END) AS seconds,"
        " SUM((SELECT COUNT(*) FROM actions x WHERE x.item_id = s.id AND x.status = 'open'))"
        " AS actions_open,"
        " SUM((SELECT COUNT(*) FROM actions x WHERE x.item_id = s.id AND x.status = 'done'))"
        " AS actions_done"
        " FROM s GROUP BY skill"
    ).fetchall()
    found = {
        r["skill"]: {
            "skill": r["skill"],
            "kept": r["kept"],
            "analyzed": r["analyzed"],
            "avg_signal": _avg(r["avg_signal"]),
            "minutes": _minutes(r["seconds"]),
            "actions_open": r["actions_open"],
            "actions_done": r["actions_done"],
        }
        for r in rows
    }
    for skill in skill_map:  # skills with no videos yet still show
        found.setdefault(
            skill,
            {
                "skill": skill,
                "kept": 0,
                "analyzed": 0,
                "avg_signal": None,
                "minutes": 0,
                "actions_open": 0,
                "actions_done": 0,
            },
        )
    return sorted(found.values(), key=lambda s: (-s["kept"], -s["analyzed"], s["skill"]))


def _funnel(conn: sqlite3.Connection) -> dict:
    by = dict(conn.execute("SELECT status, COUNT(*) FROM items GROUP BY status").fetchall())
    analysis = dict(
        conn.execute("SELECT analysis_status, COUNT(*) FROM items GROUP BY analysis_status")
    )
    marks = ",".join("?" * len(DECIDED))
    mine = f"action IN ({marks}) AND COALESCE(reason, '') != 'unavailable'"
    week = (datetime.now(UTC) - timedelta(days=7)).isoformat(timespec="seconds")
    d = conn.execute(
        f"SELECT COUNT(*) AS n, COALESCE(SUM(undone), 0) AS undone,"
        f" COALESCE(SUM(at >= ?), 0) AS week FROM decisions WHERE {mine}",
        (week, *DECIDED),
    ).fetchone()
    return {
        "inbox": by.get("inbox", 0),
        "kept": by.get("kept", 0),
        "archived": by.get("archived", 0),
        "analyzed": analysis.get("done", 0),
        "analysis_failed": analysis.get("failed", 0),
        "decisions_7d": d["week"],
        "undo_rate": round(d["undone"] / d["n"], 3) if d["n"] else None,
    }


def _keep_rows(rows) -> list[dict]:
    return [
        {
            "signal": r["signal"],
            "kept": r["kept"],
            "archived": r["archived"],
            "rate": _rate(r["kept"], r["archived"]),
        }
        for r in rows
    ]


def _signal_keep(conn: sqlite3.Connection) -> list[dict]:
    """Keep rate by the item's current signal (kept items are rescored after analysis)."""
    return _keep_rows(
        conn.execute(
            "SELECT signal, SUM(status = 'kept') AS kept, SUM(status = 'archived') AS archived"
            " FROM items WHERE signal IS NOT NULL AND status IN ('kept', 'archived')"
            " AND COALESCE(status_reason, '') != 'unavailable'"
            " GROUP BY signal ORDER BY signal"
        )
    )


def _signal_keep_clean(conn: sqlite3.Connection) -> list[dict]:
    """Keep rate by the signal saved at decision time: your latest standing decision per item."""
    marks = ",".join("?" * len(DECIDED))
    return _keep_rows(
        conn.execute(
            "WITH last AS (SELECT d.*, ROW_NUMBER() OVER (PARTITION BY item_id ORDER BY id DESC)"
            f" AS rn FROM decisions d WHERE action IN ({marks}) AND undone = 0"
            " AND COALESCE(reason, '') != 'unavailable')"
            " SELECT signal, SUM(action != 'archive') AS kept, SUM(action = 'archive') AS archived"
            " FROM last WHERE rn = 1 AND signal IS NOT NULL GROUP BY signal ORDER BY signal",
            DECIDED,
        )
    )


def _source_label(conn: sqlite3.Connection, source: str) -> str:
    if source == "youtube:watch_later":
        return "Watch Later"
    if source == "playlist:LL":
        return "Liked videos"
    if source.startswith("playlist:"):
        row = conn.execute("SELECT title FROM playlists WHERE id = ?", (source[9:],)).fetchone()
        return (row and row["title"]) or "Playlist"
    if source.startswith("channel:"):
        row = conn.execute(
            "SELECT source_ref FROM item_sources WHERE source = ? AND source_ref IS NOT NULL"
            " LIMIT 1",
            (source,),
        ).fetchone()
        return f"Pulled from {(row and row['source_ref']) or 'channel'}"
    if source == "safari":
        return "Safari bookmarks"
    if source.startswith("chrome:"):
        return "Chrome bookmarks"
    return source


def _sources(conn: sqlite3.Connection, limit: int = 15) -> list[dict]:
    rows = conn.execute(
        "SELECT s.source, SUM(i.status = 'kept') AS kept, SUM(i.status = 'archived') AS archived"
        " FROM item_sources s JOIN items i ON i.id = s.item_id"
        " WHERE i.status IN ('kept', 'archived') GROUP BY s.source"
        " ORDER BY kept + archived DESC, s.source LIMIT ?",
        (limit,),
    ).fetchall()
    return [
        {
            "source": r["source"],
            "label": _source_label(conn, r["source"]),
            "kept": r["kept"],
            "archived": r["archived"],
            "rate": _rate(r["kept"], r["archived"]),
        }
        for r in rows
    ]


def _hours(start: str | None, end: str | None) -> float | None:
    if not start or not end:
        return None
    try:
        a = datetime.fromisoformat(start.replace("Z", "+00:00"))
        b = datetime.fromisoformat(end.replace("Z", "+00:00"))
    except ValueError:
        return None
    if a.tzinfo is None:
        a = a.replace(tzinfo=UTC)
    if b.tzinfo is None:
        b = b.replace(tzinfo=UTC)
    h = (b - a).total_seconds() / 3600
    return h if h >= 0 else None


def _median(xs: list[float | None]) -> float | None:
    xs = [x for x in xs if x is not None]
    return round(statistics.median(xs), 1) if xs else None


def _latency(conn: sqlite3.Connection) -> dict:
    """Median hours from queued to notes, and from the known save time to notes."""
    rows = conn.execute(
        "SELECT i.analysis_queued_at, i.analyzed_at,"
        " COALESCE((SELECT MAX(pi.added_at) FROM playlist_items pi WHERE pi.item_id = i.id),"
        " CASE WHEN i.added_known = 1 THEN i.added_at END) AS saved_at"
        " FROM items i WHERE i.analysis_status = 'done' AND i.analyzed_at IS NOT NULL"
    ).fetchall()
    return {
        "queue_to_notes_h": _median(
            [_hours(r["analysis_queued_at"], r["analyzed_at"]) for r in rows]
        ),
        "save_to_notes_h": _median([_hours(r["saved_at"], r["analyzed_at"]) for r in rows]),
    }


def _inbox_by_tag(conn: sqlite3.Connection, limit: int = 15) -> list[dict]:
    rows = conn.execute(
        "SELECT t.tag, COUNT(*) AS inbox, AVG(i.signal) AS avg_signal"
        " FROM item_tags t JOIN items i ON i.id = t.item_id WHERE i.status = 'inbox'"
        " GROUP BY t.tag ORDER BY inbox DESC, avg_signal DESC, t.tag LIMIT ?",
        (limit,),
    )
    return [
        {"tag": r["tag"], "inbox": r["inbox"], "avg_signal": _avg(r["avg_signal"])} for r in rows
    ]


def insights(conn: sqlite3.Connection, skill_map: list[str] | None = None) -> dict:
    return {
        "skills": _skills(conn, skill_map or []),
        "funnel": _funnel(conn),
        "signal_keep": _signal_keep(conn),
        "signal_keep_clean": _signal_keep_clean(conn),
        "sources": _sources(conn),
        "latency": _latency(conn),
        "usage": usage.summary(conn),
        "inbox_by_tag": _inbox_by_tag(conn),
    }


# --- next up -----------------------------------------------------------------


def _with_skill(alias: str) -> str:
    """SQL test: the item's analysis lists the skill (one ? parameter, any case)."""
    return (
        f"EXISTS (SELECT 1 FROM json_each({_analysis(alias)}, '$.skills') j"
        " WHERE j.type = 'text' AND LOWER(j.value) = LOWER(?))"
    )


def next_watch(conn: sqlite3.Connection, skill: str | None = None) -> dict | None:
    """The inbox video with the highest signal, then the shortest (the main deck's videos)."""
    marks = ",".join("?" * len(MAIN_CATEGORIES))
    clause, args = "", ()
    if skill:
        # Shares a tag with a kept video of that skill (item_tags.tag is NOCASE).
        clause = (
            " AND items.id IN (SELECT t.item_id FROM item_tags t WHERE t.tag IN"
            " (SELECT kt.tag FROM item_tags kt JOIN items k ON k.id = kt.item_id"
            f" WHERE k.status = 'kept' AND {_with_skill('k')}))"
        )
        args = (skill,)
    row = conn.execute(
        "SELECT items.* FROM items WHERE items.status = 'inbox' AND items.available = 1"
        " AND items.prep_status IN ('done', 'failed')"
        f" AND (items.category IN ({marks}) OR items.category IS NULL)"
        f" AND NOT ({pulled_only_sql('items.id')}){clause}"
        f" ORDER BY items.signal IS NULL, items.signal DESC, {_dur('items')} IS NULL,"
        f" {_dur('items')}, items.added_at DESC LIMIT 1",
        (*MAIN_CATEGORIES, *args),
    ).fetchone()
    return card(conn, db.row_to_dict(row)) if row else None


def next_apply(conn: sqlite3.Connection, skill: str | None = None) -> dict | None:
    """An open action from a kept video, highest signal first."""
    clause, args = ("", ()) if not skill else (f" AND {_with_skill('i')}", (skill,))
    row = conn.execute(
        "SELECT a.*, i.title AS item_title FROM actions a JOIN items i ON i.id = a.item_id"
        f" WHERE a.status = 'open' AND i.status = 'kept'{clause}"
        " ORDER BY i.signal IS NULL, i.signal DESC, i.analyzed_at DESC, a.position, a.id LIMIT 1",
        args,
    ).fetchone()
    if not row:
        return None
    out = actions._row(conn, row)
    out["item_title"] = row["item_title"] or "(untitled)"
    return out


def next_up(conn: sqlite3.Connection, mode: str = "watch", skill: str | None = None) -> dict:
    if mode == "apply":
        return {"mode": "apply", "action": next_apply(conn, skill)}
    return {"mode": "watch", "item": next_watch(conn, skill)}
