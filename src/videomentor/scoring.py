"""Signal score: a 1 to 5 guess at how many clear, applicable learnings a video holds.

Made from metadata during prep so every card has one before analysis. A full
analysis replaces it with a score based on the transcript.
"""

from __future__ import annotations

import sqlite3

from . import db, llm

MAX_REASON = 120


def rules(areas: list[str], guidance: str) -> str:
    """The signal rules, shared by the quick score and the full analysis."""
    return (
        f"{guidance.strip()}\nAreas that count: {', '.join(areas)}.\n"
        "5 = several clear learnings they could apply this week; 3 = one useful idea or "
        "general advice; 1 = nothing to apply."
    )


def system(signal_rules: str) -> str:
    return f"""You help one person decide which saved YouTube videos are worth their \
time because they hold learnings they can apply in their life.
For each video, using only the metadata given, return:
- signal: 1 to 5, following these rules:
{signal_rules}
- reason: under 100 characters on why ("Three concrete scripts for hard conversations").
Judge the content, not the production value. Return one result per input id, in order."""


SCHEMA = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "signal": {"type": "integer"},
                    "reason": {"type": "string"},
                },
                "required": ["id", "signal", "reason"],
            },
        }
    },
    "required": ["items"],
}


def clamp(value: object) -> int | None:
    try:
        n = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return max(1, min(5, n))


def pending(conn: sqlite3.Connection, limit: int) -> list[dict]:
    """Unscored videos with metadata, deck first."""
    rows = conn.execute(
        "SELECT * FROM items WHERE signal_status = 'pending' AND available = 1"
        " AND enrich_status IN ('done', 'failed')"
        " ORDER BY status = 'inbox' DESC, added_at DESC LIMIT ?",
        (limit,),
    )
    return [db.row_to_dict(r) for r in rows]


def score_batch(conn: sqlite3.Connection, items: list[dict], model: str, signal_rules: str) -> int:
    from .prep import _describe  # prep imports library, which imports tagging

    if not items:
        return 0
    out = llm.structured(
        "\n\n".join(_describe(i) for i in items),
        system=system(signal_rules),
        schema=SCHEMA,
        model=model,
        step="scoring",
    )
    by_id = {r.get("id"): r for r in out.get("items", []) if isinstance(r, dict)}
    done = 0
    for item in items:
        r = by_id.get(item["id"]) or {}
        signal = clamp(r.get("signal"))
        if signal is None:
            conn.execute("UPDATE items SET signal_status = 'failed' WHERE id = ?", (item["id"],))
            continue
        # A score from a full analysis is better; never overwrite it with a guess.
        conn.execute(
            "UPDATE items SET signal = CASE WHEN signal_source = 'analysis' THEN signal ELSE ? END,"
            " signal_reason = CASE WHEN signal_source = 'analysis' THEN signal_reason ELSE ? END,"
            " signal_source = COALESCE(signal_source, 'prep'), signal_status = 'done' WHERE id = ?",
            (signal, (r.get("reason") or "")[:MAX_REASON], item["id"]),
        )
        done += 1
    conn.commit()
    return done


def requeue(conn: sqlite3.Connection) -> int:
    """Rescore every quick guess with the current rules. Analysis scores stay until re-analysis."""
    n = conn.execute(
        "UPDATE items SET signal_status = 'pending'"
        " WHERE available = 1 AND COALESCE(signal_source, 'prep') != 'analysis'"
    ).rowcount
    conn.commit()
    return n
