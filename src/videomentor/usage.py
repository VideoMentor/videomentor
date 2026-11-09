"""LLM usage: records each ``claude -p`` call in ``llm_calls`` and sums it up.

Only numbers and a prompt hash are kept, never prompt text or responses, and rows
older than ``KEEP_DAYS`` are pruned. ``cost_usd`` is what the API would charge for the
same tokens; on a Pro or Max plan it isn't billed.
"""

from __future__ import annotations

import sqlite3
import time
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path

from . import db, llm

KEEP_DAYS = 180
PRUNE_EVERY_S = 24 * 3600
COLUMNS = (
    "step",
    "item_id",
    "model",
    "ok",
    "error_kind",
    "input_tokens",
    "output_tokens",
    "cache_read_tokens",
    "cache_creation_tokens",
    "cost_usd",
    "duration_ms",
    "duration_api_ms",
    "prompt_hash",
    "prompt_chars",
)
NOT_BILLED = "Cost is API-equivalent: what the API would charge, not billed on Pro or Max plans."

_last_prune = 0.0


def _ago(days: int) -> str:
    return (datetime.now(UTC) - timedelta(days=days)).isoformat(timespec="seconds")


def prune(conn: sqlite3.Connection, days: int = KEEP_DAYS) -> int:
    n = conn.execute("DELETE FROM llm_calls WHERE at < ?", (_ago(days),)).rowcount
    conn.commit()
    return n


def record(row: dict, path: Path | None = None) -> None:
    """Write one call with its own short-lived connection (callers may hold a transaction)."""
    global _last_prune
    with closing(db.connect(path)) as conn:
        conn.execute(
            f"INSERT INTO llm_calls (at, {', '.join(COLUMNS)}) VALUES (?{', ?' * len(COLUMNS)})",
            (db.now(), *(row.get(c) for c in COLUMNS)),
        )
        conn.commit()
        if time.monotonic() - _last_prune > PRUNE_EVERY_S:
            _last_prune = time.monotonic()
            prune(conn)


def install(path: Path | None = None) -> None:
    """Record every LLM call in this process to the library (and prune old rows now)."""
    global _last_prune
    with db.session(path) as conn:
        prune(conn)
    _last_prune = time.monotonic()
    llm.set_recorder(lambda row: record(row, path))


SUMS = (
    "COUNT(*) AS calls, COALESCE(SUM(ok = 0), 0) AS failed,"
    " COALESCE(SUM(input_tokens), 0) AS input_tokens,"
    " COALESCE(SUM(output_tokens), 0) AS output_tokens,"
    " COALESCE(SUM(cache_read_tokens), 0) AS cache_read_tokens,"
    " COALESCE(SUM(cache_creation_tokens), 0) AS cache_creation_tokens,"
    " ROUND(COALESCE(SUM(cost_usd), 0), 4) AS cost_usd"
)


def totals(conn: sqlite3.Connection, since: str | None = None) -> dict:
    where, args = ("WHERE at >= ?", (since,)) if since else ("", ())
    return dict(conn.execute(f"SELECT {SUMS} FROM llm_calls {where}", args).fetchone())


def by_step(conn: sqlite3.Connection, since: str | None = None) -> list[dict]:
    where, args = ("WHERE at >= ?", (since,)) if since else ("", ())
    rows = conn.execute(
        f"SELECT step, {SUMS} FROM llm_calls {where} GROUP BY step"
        " ORDER BY cost_usd DESC, calls DESC, step",
        args,
    )
    return [dict(r) for r in rows]


def summary(conn: sqlite3.Connection) -> dict:
    """All-time and last-7-days totals, and all-time totals by step."""
    week = _ago(7)
    return {
        "since": conn.execute("SELECT MIN(at) FROM llm_calls").fetchone()[0],
        "total": totals(conn),
        "last_7d": totals(conn, week),
        "by_step": by_step(conn),
    }


def report(conn: sqlite3.Connection) -> str:
    """Plain-text tables for `vm stats`."""
    since = conn.execute("SELECT MIN(at) FROM llm_calls").fetchone()[0]
    if not since:
        return "No LLM calls recorded yet.\n" + NOT_BILLED
    head = f"{'step':<12}{'calls':>7}{'failed':>8}{'input':>12}{'output':>11}"
    head += f"{'cache read':>13}{'cache write':>13}{'cost $':>10}"
    lines = []
    for title, start in (("All time", None), ("Last 7 days", _ago(7))):
        lines += ["", title + (f" (since {since[:10]})" if start is None else ""), head]
        rows = by_step(conn, start) + [{"step": "total", **totals(conn, start)}]
        for r in rows:
            lines.append(
                f"{r['step']:<12}{r['calls']:>7,}{r['failed']:>8,}{r['input_tokens']:>12,}"
                f"{r['output_tokens']:>11,}{r['cache_read_tokens']:>13,}"
                f"{r['cache_creation_tokens']:>13,}{r['cost_usd']:>10.2f}"
            )
    lines += ["", NOT_BILLED]
    return "\n".join(lines).lstrip("\n")
