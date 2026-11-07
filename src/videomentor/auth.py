"""Pairing and sign-ins.

A device pairs once with the pairing code and gets its own random sign-in (a cookie).
Only a SHA-256 fingerprint of it is stored. A sign-in unused for SESSION_DAYS expires;
each one can be signed out on its own. Wrong pairing codes are limited to
MAX_TRIES per LOCKOUT_MINUTES for the whole app (requests arrive through one proxy).
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import re
import secrets
import sqlite3
import threading
import time
import tomllib
from collections import deque
from datetime import UTC, datetime, timedelta

from . import db
from .config import normalize_code

SESSION_DAYS = 90
MAX_TRIES = 10
LOCKOUT_MINUTES = 15
TOUCH_EVERY = timedelta(hours=1)  # write last_seen at most this often


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def code_matches(presented: str, pair_code: str) -> bool:
    a, b = normalize_code(presented), normalize_code(pair_code)
    return bool(a) and hmac.compare_digest(a.encode(), b.encode())  # bytes: any input is safe


class Lockout:
    """Wrong pairing codes: at most MAX_TRIES per LOCKOUT_MINUTES."""

    def __init__(self, tries: int = MAX_TRIES, minutes: float = LOCKOUT_MINUTES) -> None:
        self.tries, self.window = tries, minutes * 60
        self.failures: deque[float] = deque()
        self.lock = threading.Lock()

    def _trim(self, now: float) -> None:
        while self.failures and now - self.failures[0] > self.window:
            self.failures.popleft()

    def wait_seconds(self, now: float | None = None) -> int:
        """0 if pairing is open, else seconds until the oldest failure ages out."""
        now = time.time() if now is None else now
        with self.lock:
            self._trim(now)
            if len(self.failures) < self.tries:
                return 0
            return max(1, int(self.window - (now - self.failures[0])) + 1)

    def fail(self, now: float | None = None) -> None:
        with self.lock:
            self.failures.append(time.time() if now is None else now)

    def attempt(self, ok: bool, now: float | None = None) -> int:
        """Check and record one try in a single step, so parallel guesses can't slip past
        the limit. Returns 0 when the try may proceed, else seconds to wait."""
        now = time.time() if now is None else now
        with self.lock:
            self._trim(now)
            if len(self.failures) >= self.tries:
                return max(1, int(self.window - (now - self.failures[0])) + 1)
            if not ok:
                self.failures.append(now)
            return 0


def code_on_disk(fallback: str) -> str:
    """The pairing code in config.toml as written there, re-read only when the file changes.

    Read raw (not through load_settings, which would replace an old-style code)."""
    from .config import config_path

    path = config_path()
    try:
        key = (str(path), path.stat().st_mtime)
        if _code_cache.get("key") != key:
            code = str(tomllib.loads(path.read_text()).get("pair_code") or "")
            _code_cache.update(key=key, code=code)
    except (OSError, tomllib.TOMLDecodeError):
        return fallback
    return _code_cache.get("code") or fallback


_code_cache: dict = {}


def create_session(conn: sqlite3.Connection, user_agent: str | None) -> str:
    token = secrets.token_urlsafe(32)
    now = db.now()
    conn.execute(
        "INSERT INTO sessions (token_hash, created_at, last_seen, user_agent) VALUES (?, ?, ?, ?)",
        (_hash(token), now, now, (user_agent or "")[:300]),
    )
    conn.commit()
    return token


def check_session(conn: sqlite3.Connection, token: str) -> str | None:
    """The session id (fingerprint) if the sign-in is valid; refreshes last_seen."""
    if not token:
        return None
    h = _hash(token)
    row = conn.execute("SELECT last_seen FROM sessions WHERE token_hash = ?", (h,)).fetchone()
    if not row:
        return None
    last = datetime.fromisoformat(row[0])
    now = datetime.now(UTC)
    if now - last > timedelta(days=SESSION_DAYS):
        conn.execute("DELETE FROM sessions WHERE token_hash = ?", (h,))
        conn.commit()
        return None
    if now - last > TOUCH_EVERY:
        conn.execute("UPDATE sessions SET last_seen = ? WHERE token_hash = ?", (db.now(), h))
        conn.commit()
    return h


def list_sessions(conn: sqlite3.Connection, current: str | None = None) -> list[dict]:
    rows = conn.execute(
        "SELECT token_hash, created_at, last_seen, user_agent, device_hint FROM sessions"
        " ORDER BY last_seen DESC"
    ).fetchall()
    return [
        {
            "id": r[0][:16],
            "created_at": r[1],
            "last_seen": r[2],
            "device": describe_agent(r[3], r[4]),
            "current": r[0] == current,
        }
        for r in rows
    ]


def sign_out(conn: sqlite3.Connection, short_id: str) -> int:
    if not re.fullmatch(r"[0-9a-f]{16}", short_id or ""):
        return 0
    n = conn.execute(
        "DELETE FROM sessions WHERE substr(token_hash, 1, 16) = ?", (short_id,)
    ).rowcount
    conn.commit()
    return n


def sign_out_others(conn: sqlite3.Connection, keep: str | None) -> int:
    n = conn.execute("DELETE FROM sessions WHERE token_hash != ?", (keep or "",)).rowcount
    conn.commit()
    return n


HINTS = {"iPad"}  # device names the app may report about itself


def set_hint(conn: sqlite3.Connection, session_id: str, hint: str) -> bool:
    """Record what a device says it is (the app checks for an iPad behind a Mac browser)."""
    if hint not in HINTS or not session_id:
        return False
    conn.execute("UPDATE sessions SET device_hint = ? WHERE token_hash = ?", (hint, session_id))
    conn.commit()
    return True


def describe_agent(ua: str | None, hint: str | None = None) -> str:
    """'iPhone · Safari', 'Mac · Chrome', or 'Unknown device'."""
    ua = ua or ""
    if hint in HINTS:  # iPad Safari reports itself as a Mac
        ua = ua.replace("Macintosh", hint)
    device = next(
        (name for key, name in (("iPhone", "iPhone"), ("iPad", "iPad"), ("Android", "Android"),
                                ("Macintosh", "Mac"), ("Windows", "Windows"), ("Linux", "Linux")) if key in ua),
        "",
    )  # fmt: skip
    browser = next(
        (name for key, name in (("Edg/", "Edge"), ("CriOS", "Chrome"), ("Chrome/", "Chrome"),
                                ("Firefox", "Firefox"), ("Safari/", "Safari")) if key in ua),
        "",
    )  # fmt: skip
    return " · ".join(x for x in (device, browser) if x) or "Unknown device"


class RedactPairCode(logging.Filter):
    """Keep pairing codes out of the access log: /pair?code=... becomes /pair?code=…"""

    PATTERN = re.compile(r"(code=)[^&\s\"]+")

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.args, tuple):
            record.args = tuple(
                self.PATTERN.sub(r"\1…", a) if isinstance(a, str) else a for a in record.args
            )
        if isinstance(record.msg, str):
            record.msg = self.PATTERN.sub(r"\1…", record.msg)
        return True


def redact_access_log() -> None:
    access = logging.getLogger("uvicorn.access")
    if not any(isinstance(f, RedactPairCode) for f in access.filters):
        access.addFilter(RedactPairCode())
