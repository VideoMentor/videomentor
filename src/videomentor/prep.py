"""Card prep: a why-line, topic labels, and a category for each item."""

from __future__ import annotations

import sqlite3

from . import db, llm
from .library import dumps

CATEGORIES = ["learning", "music", "entertainment", "other"]

SYSTEM = """You help one person triage the YouTube videos they saved for later.
For each video, using only the metadata given, return:
- why: one plain sentence (max 120 characters) guessing what made them save it, written \
to them ("Explains...", "Shows..."). Be concrete about the payoff, not generic.
- topics: 1 to 3 short topic labels in Title Case (e.g. "Postgres", "Agent Tooling", \
"90s Dance"). Reuse the same label for the same subject across videos so related \
videos can be grouped.
- category: learning (teaches a skill or idea: talks, tutorials, explainers, \
interviews), music (songs, live performances, mixes, music videos), entertainment \
(comedy, clips, film scenes, vlogs), or other.
Return one result per input id, in the same order."""

SCHEMA = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "why": {"type": "string"},
                    "topics": {"type": "array", "items": {"type": "string"}},
                    "category": {"type": "string", "enum": CATEGORIES},
                },
                "required": ["id", "why", "topics", "category"],
            },
        }
    },
    "required": ["items"],
}


def _describe(item: dict) -> str:
    desc = (item.get("description") or "").strip().replace("\n", " ")
    parts = [
        f"id: {item['id']}",
        f"title: {item.get('title') or '?'}",
        f"channel: {item.get('channel') or '?'}",
    ]
    if item.get("duration_s"):
        parts.append(f"length: {item['duration_s'] // 60} min")
    if item.get("yt_categories"):
        parts.append(f"youtube category: {', '.join(item['yt_categories'])}")
    if item.get("tags"):
        parts.append(f"tags: {', '.join(item['tags'][:12])}")
    if desc:
        parts.append(f"description: {desc[:400]}")
    return "\n".join(parts)


def pending(conn: sqlite3.Connection, limit: int) -> list[dict]:
    """Prep waits for enrichment so the why-line has a description to work from."""
    rows = conn.execute(
        "SELECT * FROM items WHERE prep_status = 'pending' AND available = 1"
        " AND enrich_status IN ('done', 'failed') ORDER BY added_at DESC LIMIT ?",
        (limit,),
    )
    return [db.row_to_dict(r) for r in rows]


def known_topics(conn: sqlite3.Connection, limit: int = 60) -> list[str]:
    counts: dict[str, int] = {}
    for row in conn.execute("SELECT topics FROM items WHERE prep_status = 'done'"):
        for t in db.row_to_dict(row)["topics"] or []:
            counts[t] = counts.get(t, 0) + 1
    return sorted(counts, key=lambda t: -counts[t])[:limit]


def prep_batch(conn: sqlite3.Connection, items: list[dict], model: str) -> int:
    if not items:
        return 0
    topics = known_topics(conn)
    prompt = ""
    if topics:
        prompt += "Topic labels already in use (reuse when they fit): " + ", ".join(topics) + "\n\n"
    prompt += "\n\n".join(_describe(i) for i in items)
    try:
        out = llm.structured(prompt, system=SYSTEM, schema=SCHEMA, model=model)
    except llm.LLMError:
        for item in items:
            _bump_failure(conn, item["id"])
        raise
    by_id = {r["id"]: r for r in out.get("items", [])}
    done = 0
    for item in items:
        r = by_id.get(item["id"])
        if not r:
            _bump_failure(conn, item["id"])
            continue
        category = r["category"] if r["category"] in CATEGORIES else "other"
        conn.execute(
            "UPDATE items SET why = ?, topics = ?, category = ?, prep_status = 'done',"
            " updated_at = ? WHERE id = ?",
            (r["why"][:160], dumps(r["topics"][:3]), category, db.now(), item["id"]),
        )
        done += 1
    conn.commit()
    return done


MAX_ATTEMPTS = 3


def _bump_failure(conn: sqlite3.Connection, item_id: str) -> None:
    # After a few tries, mark it failed so it still reaches the deck without a why-line.
    conn.execute(
        "UPDATE items SET prep_attempts = prep_attempts + 1,"
        " prep_status = CASE WHEN prep_attempts + 1 >= ? THEN 'failed' ELSE 'pending' END"
        " WHERE id = ?",
        (MAX_ATTEMPTS, item_id),
    )
    conn.commit()
