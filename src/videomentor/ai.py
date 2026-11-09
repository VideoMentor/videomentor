"""Which AI backend runs the LLM steps, and the monthly cost cap for the API.

``ai_backend`` is "auto", "claude_code", "api" or "off". Auto uses the ``claude`` CLI
when it's on PATH, else the Anthropic API when ``ANTHROPIC_API_KEY`` is set, else
nothing. A choice that isn't available counts as off. The cap only applies to the API,
since Claude Code runs on your Claude plan.
"""

from __future__ import annotations

import os
import sqlite3
from datetime import UTC, datetime
from typing import Literal

from . import llm
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
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


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


def _check(conn: sqlite3.Connection, settings: Settings) -> tuple[Backend, float, str | None]:
    b = backend(settings)
    cost = month_cost(conn)
    if b == "off":
        return b, cost, off_reason(settings.ai_backend)
    cap = float(settings.ai_monthly_cap_usd)
    if b == "api" and cost >= cap:
        return b, cost, f"AI paused: this month's ${cap:.2f} limit is used"
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
