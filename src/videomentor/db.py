"""SQLite library: schema, connections, and row helpers.

Each caller opens its own short-lived connection; WAL mode lets the API and the
background worker read and write at the same time.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from .config import library_home

SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    id TEXT PRIMARY KEY,
    video_id TEXT NOT NULL UNIQUE,
    url TEXT NOT NULL,
    title TEXT,
    channel TEXT,
    channel_id TEXT,
    duration_s INTEGER,
    description TEXT,
    tags TEXT NOT NULL DEFAULT '[]',
    yt_categories TEXT NOT NULL DEFAULT '[]',
    upload_date TEXT,
    posted_ts INTEGER,
    channel_handle TEXT,
    channel_followers INTEGER,
    view_count INTEGER,
    -- Bumped when enrich learns new fields; older rows get refreshed (sync.ENRICH_VERSION).
    enrich_version INTEGER NOT NULL DEFAULT 1,
    chapters TEXT NOT NULL DEFAULT '[]',
    available INTEGER NOT NULL DEFAULT 1,
    added_at TEXT NOT NULL,
    -- 0 when the source has no save date (Watch Later); added_at is then the first sync.
    added_known INTEGER NOT NULL DEFAULT 0,
    wl_position INTEGER,
    status TEXT NOT NULL DEFAULT 'inbox',
    status_reason TEXT,
    priority INTEGER NOT NULL DEFAULT 0,
    why TEXT,
    topics TEXT NOT NULL DEFAULT '[]',
    category TEXT,
    enrich_status TEXT NOT NULL DEFAULT 'pending',
    prep_status TEXT NOT NULL DEFAULT 'pending',
    prep_attempts INTEGER NOT NULL DEFAULT 0,
    tag_status TEXT NOT NULL DEFAULT 'pending',
    -- 1 to 5 business-learning value; 'prep' guesses from metadata, 'analysis' replaces it.
    signal INTEGER,
    signal_reason TEXT,
    signal_source TEXT,
    signal_status TEXT NOT NULL DEFAULT 'pending',
    collaborators TEXT,
    analysis_status TEXT NOT NULL DEFAULT 'none',
    analysis TEXT,
    analysis_error TEXT,
    analysis_queued_at TEXT,
    analyzed_at TEXT,
    ready_seen INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS items_status ON items(status, prep_status, category);
CREATE INDEX IF NOT EXISTS items_analysis ON items(analysis_status, priority);

CREATE TABLE IF NOT EXISTS item_sources (
    item_id TEXT NOT NULL REFERENCES items(id),
    source TEXT NOT NULL,
    source_ref TEXT,
    first_seen TEXT NOT NULL,
    PRIMARY KEY (item_id, source)
);

CREATE TABLE IF NOT EXISTS groups (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    label TEXT NOT NULL,
    basis TEXT NOT NULL,
    anchor_item_id TEXT NOT NULL REFERENCES items(id),
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS group_items (
    group_id INTEGER NOT NULL REFERENCES groups(id),
    item_id TEXT NOT NULL REFERENCES items(id),
    PRIMARY KEY (group_id, item_id)
);

CREATE TABLE IF NOT EXISTS decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id TEXT UNIQUE,
    item_id TEXT NOT NULL REFERENCES items(id),
    action TEXT NOT NULL,
    prev_status TEXT,
    new_status TEXT,
    prev_priority INTEGER,
    new_priority INTEGER,
    prev_analysis_status TEXT,
    new_analysis_status TEXT,
    batch TEXT,
    group_id INTEGER REFERENCES groups(id),
    reason TEXT,
    undone INTEGER NOT NULL DEFAULT 0,
    -- The item's signal when you decided (it changes when kept videos are rescored).
    signal INTEGER,
    at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS decisions_item ON decisions(item_id);
CREATE INDEX IF NOT EXISTS decisions_batch ON decisions(batch);

-- Short subject tags from the tagging pass. Matching ignores case.
CREATE TABLE IF NOT EXISTS item_tags (
    item_id TEXT NOT NULL REFERENCES items(id),
    tag TEXT NOT NULL COLLATE NOCASE,
    PRIMARY KEY (item_id, tag)
);
CREATE INDEX IF NOT EXISTS item_tags_tag ON item_tags(tag);

-- Touches that aren't decisions: card flips, YouTube opens, info sheet opens.
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id TEXT UNIQUE,
    item_id TEXT NOT NULL REFERENCES items(id),
    kind TEXT NOT NULL,
    at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS events_item ON events(item_id);

-- Playlists in your YouTube library. Only enabled ones sync videos.
CREATE TABLE IF NOT EXISTS playlists (
    id TEXT PRIMARY KEY,
    title TEXT,
    owner TEXT,
    owner_channel_id TEXT,
    visibility TEXT,
    video_count INTEGER,
    -- YYYYMMDD from YouTube's "last updated".
    modified_date TEXT,
    -- From the Data API, when signed in.
    created_at TEXT,
    feed_order INTEGER,
    enabled INTEGER NOT NULL DEFAULT 0,
    -- 1 when the playlist no longer shows in the library.
    gone INTEGER NOT NULL DEFAULT 0,
    error TEXT,
    details_at TEXT,
    items_synced_at TEXT,
    dates_at TEXT,
    first_seen TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS playlist_items (
    playlist_id TEXT NOT NULL REFERENCES playlists(id),
    item_id TEXT NOT NULL REFERENCES items(id),
    position INTEGER,
    -- When the video was added to the playlist (Data API), else NULL.
    added_at TEXT,
    first_seen TEXT NOT NULL,
    PRIMARY KEY (playlist_id, item_id)
);
CREATE INDEX IF NOT EXISTS playlist_items_item ON playlist_items(item_id);

-- Captions kept after analysis, as JSON [[seconds, text], ...]; source 'none' = no captions.
CREATE TABLE IF NOT EXISTS transcripts (
    item_id TEXT PRIMARY KEY REFERENCES items(id),
    source TEXT NOT NULL,
    lines TEXT NOT NULL DEFAULT '[]',
    fetched_at TEXT NOT NULL
);

-- Tag merge list: proposals you approve, a log to undo them, and aliases so future
-- tagging uses the kept name.
CREATE TABLE IF NOT EXISTS tag_merges (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    keep TEXT NOT NULL,
    fold TEXT NOT NULL,
    reason TEXT,
    -- proposed, applied, rejected, undone
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    applied_at TEXT
);
CREATE TABLE IF NOT EXISTS tag_merge_log (
    merge_id INTEGER NOT NULL REFERENCES tag_merges(id),
    item_id TEXT NOT NULL,
    old_tag TEXT NOT NULL,
    added_keep INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS tag_aliases (
    alias TEXT PRIMARY KEY COLLATE NOCASE,
    tag TEXT NOT NULL
);

-- Milestones already celebrated (try/celebrations), so each pops up once.
CREATE TABLE IF NOT EXISTS milestones_seen (
    id TEXT PRIMARY KEY,
    seen_at TEXT NOT NULL
);

-- Actions (try/actions): "try this week" steps from analyses, as a checklist.
CREATE TABLE IF NOT EXISTS actions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id TEXT NOT NULL REFERENCES items(id),
    text TEXT NOT NULL,
    position INTEGER NOT NULL DEFAULT 0,
    -- open, done, skipped
    status TEXT NOT NULL DEFAULT 'open',
    note TEXT,
    created_at TEXT NOT NULL,
    done_at TEXT,
    UNIQUE (item_id, text)
);

-- Training modules (try/train): built from kept videos for one tag.
CREATE TABLE IF NOT EXISTS training_modules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tag TEXT NOT NULL,
    goal TEXT,
    minutes INTEGER,
    -- building, ready, failed
    status TEXT NOT NULL,
    title TEXT,
    module TEXT,
    path TEXT,
    error TEXT,
    created_at TEXT NOT NULL,
    finished_at TEXT
);

-- Channel pulls: videos brought in from a channel, not saved by you.
CREATE TABLE IF NOT EXISTS channel_pulls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    channel_id TEXT NOT NULL,
    channel TEXT,
    mode TEXT NOT NULL,
    count INTEGER,
    start TEXT,
    "end" TEXT,
    seen INTEGER NOT NULL,
    added INTEGER NOT NULL,
    via TEXT NOT NULL,
    at TEXT NOT NULL
);

-- Paired devices: one random sign-in each, stored only as a SHA-256 fingerprint.
CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    user_agent TEXT,
    -- What the device says it is when its browser hides it (iPad Safari reports "Mac").
    device_hint TEXT
);

-- One row per LLM call: numbers and a prompt hash only, never prompt text or responses.
-- cost_usd is what the API would charge; it isn't billed on Pro or Max plans.
CREATE TABLE IF NOT EXISTS llm_calls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    at TEXT NOT NULL,
    step TEXT NOT NULL,
    item_id TEXT,
    model TEXT,
    ok INTEGER NOT NULL,
    -- timeout, exit, unparseable, no_output, is_error
    error_kind TEXT,
    input_tokens INTEGER,
    output_tokens INTEGER,
    cache_read_tokens INTEGER,
    cache_creation_tokens INTEGER,
    cost_usd REAL,
    duration_ms INTEGER,
    duration_api_ms INTEGER,
    prompt_hash TEXT,
    prompt_chars INTEGER,
    -- claude_code or api; NULL on older rows means claude_code
    backend TEXT
);
CREATE INDEX IF NOT EXISTS llm_calls_step_at ON llm_calls(step, at);

CREATE TABLE IF NOT EXISTS sync_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    summary TEXT,
    error TEXT
);
"""

JSON_COLUMNS = ("tags", "yt_categories", "chapters", "topics", "analysis", "collaborators")


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def db_path() -> Path:
    return library_home() / "library.db"


def connect(path: Path | None = None) -> sqlite3.Connection:
    path = path or db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


# Columns added after the first release: (name, definition, backfill SQL run once).
ADDED_COLUMNS = [
    (
        "added_known",
        "INTEGER NOT NULL DEFAULT 0",
        "UPDATE items SET added_known = 1 WHERE id IN (SELECT item_id FROM item_sources"
        " WHERE source LIKE 'chrome:%')",
    ),
    ("posted_ts", "INTEGER", None),
    ("enrich_version", "INTEGER NOT NULL DEFAULT 1", None),
    ("channel_handle", "TEXT", None),
    ("channel_followers", "INTEGER", None),
    ("view_count", "INTEGER", None),
    ("tag_status", "TEXT NOT NULL DEFAULT 'pending'", None),
    ("signal", "INTEGER", None),
    ("signal_reason", "TEXT", None),
    ("signal_source", "TEXT", None),
    ("signal_status", "TEXT NOT NULL DEFAULT 'pending'", None),
    # JSON list of {"name", "channel_id"} for channels besides the owner.
    ("collaborators", "TEXT", None),
]


def init(conn: sqlite3.Connection) -> None:
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(items)")}
    for name, definition, backfill in ADDED_COLUMNS:
        if cols and name not in cols:
            conn.execute(f"ALTER TABLE items ADD COLUMN {name} {definition}")
            if backfill:
                conn.execute(backfill)
    conn.executescript(SCHEMA)
    session_cols = {r["name"] for r in conn.execute("PRAGMA table_info(sessions)")}
    if "device_hint" not in session_cols:
        conn.execute("ALTER TABLE sessions ADD COLUMN device_hint TEXT")
    decision_cols = {r["name"] for r in conn.execute("PRAGMA table_info(decisions)")}
    if "signal" not in decision_cols:
        conn.execute("ALTER TABLE decisions ADD COLUMN signal INTEGER")
    call_cols = {r["name"] for r in conn.execute("PRAGMA table_info(llm_calls)")}
    if "backend" not in call_cols:
        conn.execute("ALTER TABLE llm_calls ADD COLUMN backend TEXT")
    conn.commit()


@contextmanager
def session(path: Path | None = None) -> Iterator[sqlite3.Connection]:
    conn = connect(path)
    try:
        init(conn)
        yield conn
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


def row_to_dict(row: sqlite3.Row) -> dict:
    out = dict(row)
    for col in JSON_COLUMNS:
        if col in out and isinstance(out[col], str):
            try:
                out[col] = json.loads(out[col])
            except json.JSONDecodeError:
                pass
    return out


def get_item(conn: sqlite3.Connection, item_id: str) -> dict | None:
    row = conn.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()
    return row_to_dict(row) if row else None


def item_sources(conn: sqlite3.Connection, item_id: str) -> list[str]:
    rows = conn.execute(
        "SELECT source FROM item_sources WHERE item_id = ? ORDER BY first_seen, rowid", (item_id,)
    )
    return [r["source"] for r in rows]
