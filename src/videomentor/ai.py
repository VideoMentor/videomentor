"""Which AI backend runs the LLM steps, and the monthly cost cap for the API.

``ai_backend`` is "auto", "claude_code", "api" or "off". Auto uses the ``claude`` CLI
when it's on PATH, else the Anthropic API when an API key was given (``ANTHROPIC_API_KEY``
at startup, kept by ``llm_api``), else nothing. A choice that isn't available counts as
off. The cap only applies to the API, since Claude Code runs on your Claude plan.
"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from . import db, llm, llm_api
from .config import Settings

Backend = Literal["claude_code", "api", "off"]
CHOICES = ("auto", "claude_code", "api", "off")
MAX_CAP_USD = 1000.0

_settings: Settings | None = None


def configure(settings: Settings | None) -> None:
    """The Settings that ``llm.structured`` reads (the app and CLI set these at startup)."""
    global _settings
    _settings = settings


def current() -> Settings:
    return _settings if _settings is not None else Settings()


def _cli_available() -> bool:
    try:
        llm.claude_binary()
    except llm.LLMError:
        return False
    return True


def _key_available() -> bool:
    return bool(llm_api.key())


def backend(settings: Settings) -> Backend:
    choice = settings.ai_backend
    if choice == "claude_code":
        return "claude_code" if _cli_available() else "off"
    if choice == "api":
        return "api" if _key_available() else "off"
    if choice == "auto":
        if _cli_available():
            return "claude_code"
        if _key_available():
            return "api"
    return "off"


def off_reason(choice: str) -> str:
    if choice == "claude_code":
        return "AI is off: Claude Code isn't installed"
    if choice == "api":
        return "AI is off: no API key is set"
    if choice == "auto":
        return "AI is off: Claude Code isn't installed and no API key is set"
    return "AI is off"


def _month_start_utc() -> str:
    """The 1st of this local month at midnight, in the UTC format ``llm_calls.at`` uses."""
    local = datetime.now().astimezone()
    # Build midnight on the 1st as a naive local time, then let astimezone() pick the
    # UTC offset in force on that day (it can differ from today's across a DST change).
    start = datetime(local.year, local.month, 1).astimezone()
    return start.astimezone(UTC).isoformat(timespec="seconds")


def month_cost(conn: sqlite3.Connection) -> float:
    """What API calls have cost since the 1st of this local month."""
    row = conn.execute(
        "SELECT COALESCE(SUM(cost_usd), 0) FROM llm_calls WHERE backend = 'api' AND at >= ?",
        (_month_start_utc(),),
    ).fetchone()
    return float(row[0])


def paused_reason(settings: Settings) -> str:
    return f"AI paused: this month's ${float(settings.ai_monthly_cap_usd):.2f} limit is used"


# The library that usage rows go to; usage.install() sets it (None: the default library).
_usage_path: Path | None = None


def set_usage_path(path: Path | None) -> None:
    global _usage_path
    _usage_path = path


def cap_reason(settings: Settings) -> str | None:
    """The paused reason when this month's API cost has reached the cap, else None.

    ``llm.structured`` calls this before every API call. It opens its own short
    connection, as the usage recorder does, since callers may hold a transaction.
    """
    with closing(db.connect(_usage_path)) as conn:
        try:
            cost = month_cost(conn)
        except sqlite3.OperationalError as e:
            if "no such table" not in str(e):
                raise
            cost = 0.0  # a library with no llm_calls table has spent nothing
    return paused_reason(settings) if cost >= float(settings.ai_monthly_cap_usd) else None


def _check(conn: sqlite3.Connection, settings: Settings) -> tuple[Backend, float, str | None]:
    b = backend(settings)
    cost = month_cost(conn)
    if b == "off":
        return b, cost, off_reason(settings.ai_backend)
    if b == "api" and cost >= float(settings.ai_monthly_cap_usd):
        return b, cost, paused_reason(settings)
    return b, cost, None


def allowed(conn: sqlite3.Connection, settings: Settings) -> tuple[bool, str | None]:
    """Whether an AI call may run now, and if not, a plain reason to show."""
    _, _, reason = _check(conn, settings)
    return reason is None, reason


def status(conn: sqlite3.Connection, settings: Settings) -> dict:
    b, cost, reason = _check(conn, settings)
    return {
        "backend": b,
        "choice": settings.ai_backend,
        "cap_usd": float(settings.ai_monthly_cap_usd),
        "month_cost_usd": round(cost, 4),
        "paused": reason is not None,
        "reason": reason,
    }
