"""Triage logic: items, decisions, undo, groups, decks.

Every status change goes through ``_record`` so it lands in the decisions log and
can be undone. Nothing is ever deleted.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from collections import Counter
from datetime import UTC, datetime, timedelta

from . import db, tagging
from .sources.youtube import thumbnail_url, watch_url

MAIN_CATEGORIES = ("learning", "other")
MUSIC_CATEGORIES = ("music", "entertainment")
GROUP_LIMIT = 12


class UndoConflict(Exception):
    """The decision isn't the latest one for its item, so undoing it would lose later work."""


class NotFound(Exception):
    pass


# --- cards ---------------------------------------------------------------


def posted(item: dict) -> tuple[str | None, bool]:
    """Publish time as ISO (UTC) when exact, else the YYYY-MM-DD upload date."""
    if item.get("posted_ts"):
        return datetime.fromtimestamp(item["posted_ts"], UTC).isoformat(), True
    d = item.get("upload_date")
    if d and len(d) == 8 and d.isdigit():
        return f"{d[:4]}-{d[4:6]}-{d[6:]}", False
    return None, False


def saved_labels(conn: sqlite3.Connection, item_id: str) -> list[str]:
    """Where a video was saved, in words: Watch Later, playlist names, bookmarks."""
    rows = conn.execute(
        "SELECT s.source, s.source_ref, p.title FROM item_sources s LEFT JOIN playlists p"
        " ON s.source = 'playlist:' || p.id WHERE s.item_id = ? ORDER BY s.first_seen, s.rowid",
        (item_id,),
    )
    labels: list[str] = []
    for r in rows:
        src = r["source"]
        if src == "youtube:watch_later":
            label = "Watch Later"
        elif src.startswith("playlist:"):
            label = r["title"] or "Playlist"
        elif src.startswith("channel:"):
            label = f"Pulled from {r['source_ref'] or 'channel'}"
        elif src == "safari":
            label = "Safari bookmark"
        elif src.startswith("chrome:"):
            label = "Chrome bookmark"
        else:
            label = src
        if label not in labels:
            labels.append(label)
    return labels


def saved(conn: sqlite3.Connection, item: dict) -> tuple[str | None, str | None]:
    """The best known save time and where: a playlist's save date (Data API), else a
    bookmark's date. Watch Later has none: YouTube doesn't share it."""
    row = conn.execute(
        "SELECT pi.added_at, p.title FROM playlist_items pi JOIN playlists p ON p.id = pi.playlist_id"
        " WHERE pi.item_id = ? AND pi.added_at IS NOT NULL ORDER BY pi.added_at DESC LIMIT 1",
        (item["id"],),
    ).fetchone()
    if row:
        return row["added_at"], row["title"]
    if item.get("added_known"):
        src = conn.execute(
            "SELECT source FROM item_sources WHERE item_id = ?"
            " AND (source = 'safari' OR source LIKE 'chrome:%') LIMIT 1",
            (item["id"],),
        ).fetchone()
        where = None
        if src:
            where = "Safari bookmarks" if src["source"] == "safari" else "Chrome bookmarks"
        return item["added_at"], where
    return None, None


def card(conn: sqlite3.Connection, item: dict) -> dict:
    analysis = item.get("analysis") if isinstance(item.get("analysis"), dict) else None
    summary = (analysis or {}).get("summary")
    posted_at, posted_exact = posted(item)
    saved_at, saved_where = saved(conn, item)
    return {
        "id": item["id"],
        "video_id": item["video_id"],
        "url": item["url"],
        "title": item.get("title") or "(untitled)",
        "channel": item.get("channel"),
        "channel_id": item.get("channel_id"),
        "collaborators": item.get("collaborators") or [],
        "posted_at": posted_at,
        "posted_exact": posted_exact,
        "duration_s": item.get("duration_s"),
        "thumbnail": thumbnail_url(item["video_id"]),
        "added_at": item["added_at"] if item.get("added_known") else None,
        "saved_at": saved_at,
        "saved_where": saved_where,
        "why": item.get("why"),
        "topics": item.get("topics") or [],
        "tags": tagging.item_tags(conn, item["id"]),
        "category": item.get("category"),
        "status": item["status"],
        "priority": item["priority"],
        "analysis_status": item["analysis_status"],
        "sources": db.item_sources(conn, item["id"]),
        "saved_in_labels": saved_labels(conn, item["id"]),
        "summary_short": (summary[:200] + "…") if summary and len(summary) > 200 else summary,
        "signal": item.get("signal"),
        "signal_reason": item.get("signal_reason"),
        "signal_source": item.get("signal_source"),
        "key_moment": (analysis or {}).get("key_moment"),
        "core_idea": (analysis or {}).get("core_idea"),
        "skills": (analysis or {}).get("skills") or [],
    }


def item_detail(conn: sqlite3.Connection, item_id: str) -> dict:
    item = db.get_item(conn, item_id)
    if not item:
        raise NotFound(item_id)
    rows = conn.execute(
        "SELECT id, action, new_status, reason, undone, at FROM decisions"
        " WHERE item_id = ? ORDER BY id",
        (item_id,),
    )
    return card(conn, item) | {
        "description": item.get("description") or "",
        "upload_date": item.get("upload_date"),
        "channel_handle": item.get("channel_handle"),
        "channel_followers": item.get("channel_followers"),
        "view_count": item.get("view_count"),
        "yt_tags": item.get("tags") or [],
        "yt_categories": item.get("yt_categories") or [],
        "saved_in": [
            dict(r)
            for r in conn.execute(
                "SELECT source, source_ref, first_seen FROM item_sources WHERE item_id = ?"
                " ORDER BY first_seen, rowid",
                (item_id,),
            )
        ],
        "chapters": item.get("chapters") or [],
        "analysis": item.get("analysis"),
        "analysis_error": item.get("analysis_error"),
        "decisions": [dict(r) for r in rows],
    }


# --- ingest --------------------------------------------------------------


def upsert_item(
    conn: sqlite3.Connection,
    video_id: str,
    *,
    source: str,
    source_ref: str | None = None,
    title: str | None = None,
    channel: str | None = None,
    channel_id: str | None = None,
    duration_s: int | None = None,
    added_at: str | None = None,
    wl_position: int | None = None,
    available: bool = True,
) -> bool:
    """Insert or refresh one video. Returns True if it was new."""
    item_id = f"yt:{video_id}"
    ts = db.now()
    existing = db.get_item(conn, item_id)
    if existing is None:
        conn.execute(
            "INSERT INTO items (id, video_id, url, title, channel, channel_id, duration_s,"
            " available, added_at, added_known, wl_position, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                item_id,
                video_id,
                watch_url(video_id),
                title,
                channel,
                channel_id,
                duration_s,
                int(available),
                added_at or ts,
                int(bool(added_at)),
                wl_position,
                ts,
                ts,
            ),
        )
    else:
        conn.execute(
            "UPDATE items SET title = COALESCE(title, ?), channel = COALESCE(channel, ?),"
            " channel_id = COALESCE(channel_id, ?), duration_s = COALESCE(duration_s, ?),"
            " wl_position = COALESCE(?, wl_position), available = ?,"
            " added_known = MAX(added_known, ?), added_at = MIN(added_at, ?), updated_at = ?"
            " WHERE id = ?",
            (
                title,
                channel,
                channel_id,
                duration_s,
                wl_position,
                int(available and bool(existing["available"])),
                int(bool(added_at)),
                added_at or existing["added_at"],
                ts,
                item_id,
            ),
        )
    conn.execute(
        "INSERT OR IGNORE INTO item_sources (item_id, source, source_ref, first_seen)"
        " VALUES (?, ?, ?, ?)",
        (item_id, source, source_ref, ts),
    )
    item = db.get_item(conn, item_id)
    if not item["available"] and item["status"] == "inbox":
        mark_unavailable(conn, item_id)
    return existing is None


def mark_unavailable(conn: sqlite3.Connection, item_id: str) -> None:
    """Auto-archive a private or deleted video, logged and reversible."""
    conn.execute(
        "UPDATE items SET available = 0, prep_status = 'skipped', enrich_status = 'skipped'"
        " WHERE id = ?",
        (item_id,),
    )
    item = db.get_item(conn, item_id)
    if item["status"] == "inbox":
        _record(conn, item, "archive", reason="unavailable")


# --- decisions -----------------------------------------------------------


def _transition(item: dict, action: str) -> tuple[str, int, str]:
    priority, analysis = item["priority"], item["analysis_status"]
    idle = analysis in ("none", "queued", "failed")
    if action == "keep":
        return "kept", priority, ("queued" if analysis in ("none", "failed") else analysis)
    if action == "prioritize":
        return "kept", 1, ("queued" if idle else analysis)
    if action == "archive":
        return "archived", 0, ("none" if analysis == "queued" else analysis)
    raise ValueError(f"unknown action {action!r}")


def _record(
    conn: sqlite3.Connection,
    item: dict,
    action: str,
    *,
    client_id: str | None = None,
    at: str | None = None,
    group_id: int | None = None,
    batch: str | None = None,
    reason: str | None = None,
) -> int:
    new_status, new_priority, new_analysis = _transition(item, action)
    ts = db.now()
    cur = conn.execute(
        "INSERT INTO decisions (client_id, item_id, action, prev_status, new_status,"
        " prev_priority, new_priority, prev_analysis_status, new_analysis_status,"
        " batch, group_id, reason, signal, at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            client_id,
            item["id"],
            action,
            item["status"],
            new_status,
            item["priority"],
            new_priority,
            item["analysis_status"],
            new_analysis,
            batch,
            group_id,
            reason,
            item.get("signal"),
            at or ts,
        ),
    )
    queued_at = ts if new_analysis == "queued" and item["analysis_status"] != "queued" else None
    conn.execute(
        "UPDATE items SET status = ?, status_reason = ?, priority = ?, analysis_status = ?,"
        " analysis_queued_at = COALESCE(?, analysis_queued_at), updated_at = ? WHERE id = ?",
        (new_status, reason, new_priority, new_analysis, queued_at, ts, item["id"]),
    )
    return cur.lastrowid


def decide(
    conn: sqlite3.Connection, item_id: str, action: str, client_id: str, at: str | None = None
) -> dict:
    """Apply keep, archive, or prioritize. Retrying the same client_id is a no-op."""
    prior = conn.execute(
        "SELECT id, item_id FROM decisions WHERE client_id = ?", (client_id,)
    ).fetchone()
    if prior:
        return {"decision_id": prior["id"], "item": card(conn, db.get_item(conn, prior["item_id"]))}
    item = db.get_item(conn, item_id)
    if not item:
        raise NotFound(item_id)
    decision_id = _record(conn, item, action, client_id=client_id, at=at)
    return {"decision_id": decision_id, "item": card(conn, db.get_item(conn, item_id))}


def _revert(conn: sqlite3.Connection, r: sqlite3.Row, ts: str) -> dict:
    """Roll one decision back and log the undo. Returns the item's card."""
    item = db.get_item(conn, r["item_id"])
    # Only roll back the analysis state if the worker hasn't moved it since.
    analysis = item["analysis_status"]
    if analysis == r["new_analysis_status"]:
        analysis = r["prev_analysis_status"]
    conn.execute(
        "UPDATE items SET status = ?, priority = ?, analysis_status = ?,"
        " status_reason = NULL, updated_at = ? WHERE id = ?",
        (r["prev_status"], r["prev_priority"], analysis, ts, r["item_id"]),
    )
    conn.execute("UPDATE decisions SET undone = 1 WHERE id = ?", (r["id"],))
    conn.execute(
        "INSERT INTO decisions (item_id, action, prev_status, new_status, reason, at)"
        " VALUES (?, 'undo', ?, ?, ?, ?)",
        (r["item_id"], r["new_status"], r["prev_status"], f"undo #{r['id']}", ts),
    )
    return card(conn, db.get_item(conn, r["item_id"]))


def undo(conn: sqlite3.Connection, decision_id: int | None = None) -> dict:
    """Revert one decision (or the newest), plus the rest of its batch for group decisions."""
    if decision_id is None:
        row = conn.execute(
            "SELECT * FROM decisions WHERE undone = 0 AND action != 'undo'"
            " AND COALESCE(reason, '') != 'unavailable' ORDER BY id DESC LIMIT 1"
        ).fetchone()
    else:
        row = conn.execute("SELECT * FROM decisions WHERE id = ?", (decision_id,)).fetchone()
    if row is None or row["action"] == "undo":
        return {"undone": [], "items": []}
    if row["undone"]:
        return {"undone": [], "items": [card(conn, db.get_item(conn, row["item_id"]))]}
    rows = [row]
    if row["batch"]:
        rows = conn.execute(
            "SELECT * FROM decisions WHERE batch = ? AND undone = 0 ORDER BY id DESC",
            (row["batch"],),
        ).fetchall()
    for r in rows:
        later = conn.execute(
            "SELECT 1 FROM decisions WHERE item_id = ? AND id > ? AND undone = 0"
            " AND (batch IS NULL OR batch != ?)",
            (r["item_id"], r["id"], r["batch"] or ""),
        ).fetchone()
        if later:
            raise UndoConflict(f"decision {r['id']} has a later decision for {r['item_id']}")
    ts = db.now()
    items = [_revert(conn, r, ts) for r in rows]
    return {"undone": [r["id"] for r in rows], "items": items}


def undo_batch(conn: sqlite3.Connection, batch: str) -> dict:
    """Revert what can be reverted in one batch; items decided again since stay as they are.

    Returns the ids undone, their cards, and how many were skipped.
    """
    rows = conn.execute(
        "SELECT * FROM decisions WHERE batch = ? AND undone = 0 AND action != 'undo'"
        " ORDER BY id DESC",
        (batch,),
    ).fetchall()
    ts = db.now()
    undone, items, skipped = [], [], 0
    for r in rows:
        later = conn.execute(
            "SELECT 1 FROM decisions WHERE item_id = ? AND id > ? AND undone = 0"
            " AND (batch IS NULL OR batch != ?)",
            (r["item_id"], r["id"], batch),
        ).fetchone()
        if later:
            skipped += 1
            continue
        items.append(_revert(conn, r, ts))
        undone.append(r["id"])
    return {"undone": undone, "items": items, "skipped": skipped}


def nl_where(prefix: str = "", include_unprepped: bool = False) -> str:
    """SQL for Not for learning: inbox music and entertainment the deck would deal.

    The deck, the counts and the bulk archive all use this, so the numbers match.
    Videos only pulled from a channel are left out, as in the main deck.
    """
    cats = "','".join(MUSIC_CATEGORIES)
    return (
        f"{prefix}status = 'inbox' AND {prefix}available = 1"
        f" AND {_dealable(prefix, include_unprepped)} AND {prefix}category IN ('{cats}')"
        f" AND NOT ({pulled_only_sql(prefix + 'id')})"
    )


def not_for_learning_counts(
    conn: sqlite3.Connection, older_than_days: int = 30, include_unprepped: bool = False
) -> dict:
    """Inbox music and entertainment, and how many were saved long enough ago."""
    cutoff = (datetime.now(UTC) - timedelta(days=older_than_days)).isoformat(timespec="seconds")
    where = nl_where("", include_unprepped)
    return {
        "inbox": conn.execute(f"SELECT COUNT(*) FROM items WHERE {where}").fetchone()[0],
        "older": conn.execute(
            f"SELECT COUNT(*) FROM items WHERE {where} AND added_at < ?", (cutoff,)
        ).fetchone()[0],
    }


def archive_not_for_learning(
    conn: sqlite3.Connection, older_than_days: int = 30, include_unprepped: bool = False
) -> dict:
    """Archive old Not for learning videos as one batch, so one Undo brings them back."""
    cutoff = (datetime.now(UTC) - timedelta(days=older_than_days)).isoformat(timespec="seconds")
    where = nl_where("", include_unprepped)
    rows = conn.execute(
        f"SELECT * FROM items WHERE {where} AND added_at < ? ORDER BY added_at", (cutoff,)
    ).fetchall()
    batch = f"nl-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:6]}"
    for r in rows:
        _record(conn, db.row_to_dict(r), "archive", batch=batch, reason="not for learning")
    return {"archived": len(rows), "batch": batch}


def pulled_only_sql(col: str = "id") -> str:
    """SQL test for videos that came only from a channel pull (no save, playlist or bookmark).

    Items with no source rows at all (for example removed from their playlist) still count
    as saves, so they stay in All saves.
    """
    return (
        f"{col} IN (SELECT item_id FROM item_sources WHERE source LIKE 'channel:%')"
        f" AND {col} NOT IN (SELECT item_id FROM item_sources WHERE source NOT LIKE 'channel:%')"
    )


# --- groups --------------------------------------------------------------


def create_group(conn: sqlite3.Connection, anchor_item_id: str) -> dict:
    """Gather inbox items sharing a topic or channel with the anchor."""
    anchor = db.get_item(conn, anchor_item_id)
    if not anchor:
        raise NotFound(anchor_item_id)
    anchor_topics = {t.lower() for t in anchor.get("topics") or []}
    scored: list[tuple[int, dict, set[str], bool]] = []
    # Groups stay on the anchor's side: saves with saves, pulled videos with pulled ones.
    pulled = conn.execute(
        f"SELECT 1 FROM items WHERE id = ? AND {pulled_only_sql()}", (anchor_item_id,)
    ).fetchone()
    side = pulled_only_sql() if pulled else f"NOT ({pulled_only_sql()})"
    rows = conn.execute(
        f"SELECT * FROM items WHERE status = 'inbox' AND available = 1 AND id != ? AND {side}",
        (anchor_item_id,),
    )
    for row in rows:
        other = db.row_to_dict(row)
        shared = anchor_topics & {t.lower() for t in other.get("topics") or []}
        same_channel = bool(
            (anchor.get("channel_id") and anchor["channel_id"] == other.get("channel_id"))
            or (anchor.get("channel") and anchor["channel"] == other.get("channel"))
        )
        score = 2 * len(shared) + (1 if same_channel else 0)
        if score:
            scored.append((score, other, shared, same_channel))
    scored.sort(key=lambda s: (-s[0], s[1]["added_at"]), reverse=False)
    members = scored[:GROUP_LIMIT]

    topic_votes = Counter(t for _, _, shared, _ in members for t in shared)
    channel_votes = sum(1 for *_, same in members if same)
    if topic_votes and topic_votes.most_common(1)[0][1] >= channel_votes:
        top = topic_votes.most_common(1)[0][0]
        label = next((t for t in anchor.get("topics") or [] if t.lower() == top), top)
        basis = "topic"
    elif channel_votes:
        label, basis = anchor.get("channel") or "Same channel", "channel"
    else:
        label, basis = (anchor.get("topics") or ["Related"])[0], "topic"

    cur = conn.execute(
        "INSERT INTO groups (label, basis, anchor_item_id, created_at) VALUES (?, ?, ?, ?)",
        (label, basis, anchor_item_id, db.now()),
    )
    group_id = cur.lastrowid
    for item_id in [anchor_item_id] + [m[1]["id"] for m in members]:
        conn.execute(
            "INSERT INTO group_items (group_id, item_id) VALUES (?, ?)", (group_id, item_id)
        )
    return {
        "group": {"id": group_id, "label": label, "basis": basis},
        "items": [card(conn, anchor)] + [card(conn, m[1]) for m in members],
    }


def decide_group(conn: sqlite3.Connection, group_id: int, action: str, client_id: str) -> dict:
    """Keep or archive every group member still in the inbox, as one undoable batch."""
    if action not in ("keep", "archive"):
        raise ValueError(action)
    if not conn.execute("SELECT 1 FROM groups WHERE id = ?", (group_id,)).fetchone():
        raise NotFound(str(group_id))
    member_ids = [
        r["item_id"]
        for r in conn.execute("SELECT item_id FROM group_items WHERE group_id = ?", (group_id,))
    ]
    decision_ids, items = [], []
    for item_id in member_ids:
        sub_id = f"{client_id}:{item_id}"
        prior = conn.execute("SELECT id FROM decisions WHERE client_id = ?", (sub_id,)).fetchone()
        if prior:
            decision_ids.append(prior["id"])
        else:
            item = db.get_item(conn, item_id)
            if item["status"] != "inbox":
                continue
            decision_ids.append(
                _record(conn, item, action, client_id=sub_id, group_id=group_id, batch=client_id)
            )
        items.append(card(conn, db.get_item(conn, item_id)))
    return {"decision_ids": decision_ids, "items": items}


# --- views ---------------------------------------------------------------


# Sortable "YYYY-MM-DDTHH:MM:SS" keys (first 19 chars, so "Z" and "+00:00" compare alike).
POSTED_KEY = (
    "(CASE WHEN items.posted_ts IS NOT NULL"
    " THEN strftime('%Y-%m-%dT%H:%M:%S', items.posted_ts, 'unixepoch')"
    " WHEN length(items.upload_date) = 8 THEN substr(items.upload_date, 1, 4) || '-'"
    " || substr(items.upload_date, 5, 2) || '-' || substr(items.upload_date, 7, 2) || 'T00:00:00'"
    " END)"
)
SAVED_KEY = (
    "substr(COALESCE((SELECT MAX(x.added_at) FROM playlist_items x WHERE x.item_id = items.id),"
    " CASE WHEN items.added_known = 1 THEN items.added_at END), 1, 19)"
)


def deck(
    conn: sqlite3.Connection,
    which: str,
    n: int,
    exclude: list[str],
    source: str = "all",
    sort: str = "default",
    direction: str = "desc",
    start: str | None = None,
    include_unprepped: bool = False,
) -> list[dict]:
    """Inbox cards for the main or music deck, from all saves or one source.

    include_unprepped (for when AI can't run) also deals enriched items that card prep
    hasn't reached, showing title, channel and thumbnail without a why-line.

    source: "all", "wl" (Watch Later), "playlists" (every enabled playlist, newest
    save first), "nl" (Not for learning: music and entertainment you saved, from any
    source except channel pulls), or "pl:<id>" (one playlist: newest save first when the
    API dates are known, else its stored order).
    """
    # "nl" (Not for learning) is a source of the main deck. It deals the same cards the
    # counts and the bulk archive use (nl_where). The "music" deck is the older way to ask
    # for music and entertainment and keeps its own query.
    nl = source == "nl"
    music = which == "music"
    categories = () if nl else MUSIC_CATEGORIES if music else MAIN_CATEGORIES
    marks = ",".join("?" * len(categories))
    excl = ",".join("?" * len(exclude)) or "''"
    # Items whose prep failed still show (without a why-line) so a broken LLM never
    # empties the deck; they have no category and fall into the main deck.
    category_clause = (
        nl_where("items.", include_unprepped)
        if nl
        else f"items.category IN ({marks})"
        if music
        else f"(items.category IN ({marks}) OR items.category IS NULL)"
    )
    join, order, extra = "", "items.added_at DESC, items.wl_position ASC", ()
    # Videos only pulled from a channel aren't saves: they show under their channel source.
    saves_only = f" AND NOT ({pulled_only_sql('items.id')})"
    if source == "all":
        join = ""
    if source.startswith("ch:"):
        join = " JOIN item_sources cs ON cs.item_id = items.id AND cs.source = 'channel:' || ?"
        extra = (source[3:],)
        order = f"{POSTED_KEY} IS NULL, {POSTED_KEY} DESC"
        saves_only = ""
    elif source == "wl":
        join = " JOIN item_sources s ON s.item_id = items.id AND s.source = 'youtube:watch_later'"
        order = "items.wl_position ASC, items.added_at DESC"
    elif source == "playlists":
        join = (
            " JOIN (SELECT pi.item_id, MAX(COALESCE(pi.added_at, pi.first_seen)) AS saved,"
            " MIN(p.feed_order * 100000 + COALESCE(pi.position, 0)) AS ord"
            " FROM playlist_items pi JOIN playlists p ON p.id = pi.playlist_id"
            " WHERE p.enabled = 1 GROUP BY pi.item_id) src ON src.item_id = items.id"
        )
        order = "src.saved DESC, src.ord ASC"
    elif source.startswith("pl:"):
        join = " JOIN playlist_items pi ON pi.item_id = items.id AND pi.playlist_id = ?"
        extra = (source[3:],)
        order = "pi.added_at IS NULL, pi.added_at DESC, pi.position ASC"
    # Optional date sort: posted or saved, newest or oldest first, from a start date.
    date_clause, date_args = "", ()
    if sort in ("posted", "saved"):
        key = POSTED_KEY if sort == "posted" else SAVED_KEY
        asc = direction == "asc"
        if start:
            # Forward: on or after the day. Backward: on or before it (whole day).
            date_clause = f" AND {key} >= ?" if asc else f" AND {key} <= ?"
            date_args = (f"{start}T00:00:00",) if asc else (f"{start}T23:59:59",)
        order = f"{key} IS NULL, {key} {'ASC' if asc else 'DESC'}, {order}"
    rows = conn.execute(
        f"SELECT items.* FROM items{join} WHERE items.status = 'inbox' AND items.available = 1"
        f" AND {_dealable('items.', include_unprepped)} AND {category_clause}"
        f" AND items.id NOT IN ({excl}){date_clause}{saves_only}"
        f" ORDER BY {order} LIMIT ?",
        (*extra, *categories, *exclude, *date_args, n),
    )
    return [card(conn, db.row_to_dict(r)) for r in rows]


# Decision reasons that aren't your own triage: the automatic archive of unavailable
# videos and the bulk archive of Not for learning. Counts and dates leave them out.
NOT_MINE = "('unavailable', 'not for learning')"

# When you last decided on an item yourself (not undone, not an automatic or bulk archive).
DECIDED_SQL = (
    "(SELECT MAX(d.at) FROM decisions d WHERE d.item_id = items.id AND d.undone = 0"
    f" AND d.action != 'undo' AND COALESCE(d.reason, '') NOT IN {NOT_MINE})"
)


def ready(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        f"SELECT *, {DECIDED_SQL} AS decided_at FROM items WHERE analysis_status = 'done'"
        " AND ready_seen = 0 AND status = 'kept' ORDER BY priority DESC, analyzed_at DESC"
    )
    return [
        card(conn, db.row_to_dict(r))
        | {"decided_at": r["decided_at"], "analyzed_at": r["analyzed_at"]}
        for r in rows
    ]


def mark_seen(conn: sqlite3.Connection, item_id: str) -> None:
    conn.execute("UPDATE items SET ready_seen = 1 WHERE id = ?", (item_id,))


def library_items(conn: sqlite3.Connection, status: str, q: str | None, limit: int = 2000) -> list:
    """Kept, archived, or both ("processed"), each with when you decided it.

    Automatic archives of unavailable videos aren't your decisions, so they're left out
    of "processed" and "archived".
    """
    decided = DECIDED_SQL
    if status == "processed":
        sql = f"SELECT *, {decided} AS decided_at FROM items WHERE status IN ('kept', 'archived')"
        params: list = []
    else:
        sql = f"SELECT *, {decided} AS decided_at FROM items WHERE status = ?"
        params = [status]
    if status in ("processed", "archived"):
        sql += " AND COALESCE(status_reason, '') != 'unavailable'"
    if q:
        like = f"%{q}%"
        sql += (
            " AND (title LIKE ? OR channel LIKE ? OR why LIKE ? OR topics LIKE ?"
            " OR id IN (SELECT item_id FROM item_tags WHERE tag LIKE ?))"
        )
        params += [like] * 5
    sql += " ORDER BY decided_at DESC, updated_at DESC LIMIT ?"
    params.append(limit)
    return [
        card(conn, db.row_to_dict(r))
        | {"decided_at": r["decided_at"], "analyzed_at": r["analyzed_at"]}
        for r in conn.execute(sql, params)
    ]


# --- touches, tags, channels -------------------------------------

EVENT_KINDS = ("flip", "open", "info")


def record_events(conn: sqlite3.Connection, events: list[dict]) -> int:
    """Store touch events; repeats (same client_id) and unknown items are skipped."""
    stored = 0
    for e in events:
        if e["kind"] not in EVENT_KINDS or not db.get_item(conn, e["item_id"]):
            continue
        cur = conn.execute(
            "INSERT OR IGNORE INTO events (client_id, item_id, kind, at) VALUES (?, ?, ?, ?)",
            (e["client_id"], e["item_id"], e["kind"], e.get("at") or db.now()),
        )
        stored += cur.rowcount
    return stored


# Everything you did yourself: decisions (not undone, not automatic or bulk) plus touch events.
TOUCHES_SQL = f"""
    SELECT item_id, action, at FROM decisions
     WHERE undone = 0 AND action != 'undo' AND COALESCE(reason, '') NOT IN {NOT_MINE}
    UNION ALL
    SELECT item_id, kind AS action, at FROM events
"""


def tag_history(conn: sqlite3.Connection, tag: str, limit: int = 200) -> dict:
    """Videos with this tag that you have touched, newest touch first."""
    row = conn.execute(
        "SELECT tag, COUNT(*) AS n FROM item_tags WHERE tag = ? GROUP BY tag", (tag,)
    ).fetchone()
    if not row:
        return {"tag": tag, "total": 0, "related": [], "items": []}
    related = conn.execute(
        "SELECT o.tag, COUNT(*) AS n FROM item_tags t JOIN item_tags o"
        " ON o.item_id = t.item_id AND o.tag != t.tag WHERE t.tag = ?"
        " GROUP BY o.tag ORDER BY n DESC, o.tag LIMIT 8",
        (tag,),
    ).fetchall()
    touched = conn.execute(
        f"WITH touches AS ({TOUCHES_SQL}),"
        " ranked AS (SELECT item_id, action, at, COUNT(*) OVER (PARTITION BY item_id) AS n,"
        " ROW_NUMBER() OVER (PARTITION BY item_id ORDER BY at DESC) AS rn FROM touches)"
        " SELECT r.item_id, r.action, r.at, r.n FROM ranked r"
        " JOIN item_tags t ON t.item_id = r.item_id AND t.tag = ?"
        " WHERE r.rn = 1 ORDER BY r.at DESC LIMIT ?",
        (tag, limit),
    ).fetchall()
    items = [
        card(conn, db.get_item(conn, r["item_id"]))
        | {"last_action": r["action"], "last_at": r["at"], "touches": r["n"]}
        for r in touched
    ]
    return {
        "tag": row["tag"],
        "total": row["n"],
        "related": [{"tag": r["tag"], "count": r["n"]} for r in related],
        "items": items,
    }


def channel_summary(
    conn: sqlite3.Connection, channel_id: str | None = None, name: str | None = None
) -> dict:
    """A channel's videos in the library: ones it owns, plus ones it is credited on as a
    collaborator."""
    if channel_id:
        owns, arg = "channel_id = ?", channel_id
        collab = '"channel_id": ' + json.dumps(channel_id)
    elif name:
        owns, arg = "channel = ?", name
        collab = '"name": ' + json.dumps(name, ensure_ascii=False)  # as stored by dumps()
    else:
        raise NotFound("channel")
    # collaborators is stored as JSON text written by json.dumps, so the key/value pair
    # appears verbatim; instr() avoids LIKE wildcards in names.
    where = f"({owns} OR instr(COALESCE(collaborators, ''), ?) > 0)"
    rows = conn.execute(
        f"SELECT channel, channel_id, channel_handle, channel_followers, collaborators, status"
        f" FROM items WHERE {where} AND available = 1",
        (arg, collab),
    ).fetchall()
    if not rows:
        raise NotFound(arg)
    statuses = Counter(r["status"] for r in rows)
    owned = [
        r for r in rows if (r["channel_id"] == channel_id if channel_id else r["channel"] == name)
    ]

    def first(col: str):
        return next((r[col] for r in owned if r[col]), None)

    credited = None  # how a collaborator-only channel is named in the videos it's on
    if not owned:
        for r in rows:
            for c in json.loads(r["collaborators"] or "[]"):
                if (channel_id and c.get("channel_id") == channel_id) or (
                    not channel_id and c.get("name") == name
                ):
                    credited = c
                    break
            if credited:
                break

    recent = conn.execute(
        f"SELECT * FROM items WHERE {where} AND available = 1 ORDER BY added_at DESC LIMIT 100",
        (arg, collab),
    )
    return {
        "items": [card(conn, db.row_to_dict(r)) for r in recent],
        "channel": first("channel") or (credited or {}).get("name") or name,
        "channel_id": first("channel_id") or (credited or {}).get("channel_id") or channel_id,
        "handle": first("channel_handle"),
        "followers": first("channel_followers"),
        "counts": {
            "saved": len(rows),
            "kept": statuses["kept"],
            "archived": statuses["archived"],
            "inbox": statuses["inbox"],
        },
    }


def _dealable(prefix: str = "", include_unprepped: bool = False) -> str:
    """SQL for items whose prep lets them reach the deck."""
    clause = f"{prefix}prep_status IN ('done', 'failed')"
    if include_unprepped:
        clause = (
            f"({clause} OR ({prefix}prep_status = 'pending' AND {prefix}enrich_status = 'done'))"
        )
    return clause


def counts(conn: sqlite3.Connection, include_unprepped: bool = False) -> dict:
    """Library counts. include_unprepped counts the inbox the way the deck deals it."""

    def one(sql: str) -> int:
        return conn.execute(sql).fetchone()[0]

    main = "','".join(MAIN_CATEGORIES)
    music = "','".join(MUSIC_CATEGORIES)
    dealable = _dealable("", include_unprepped)
    triageable = f"status = 'inbox' AND available = 1 AND {dealable} AND NOT ({pulled_only_sql()})"
    pulled_only = f"status = 'inbox' AND available = 1 AND {dealable} AND {pulled_only_sql()}"
    return {
        "total": one("SELECT COUNT(*) FROM items"),
        "inbox": one(
            f"SELECT COUNT(*) FROM items WHERE {triageable}"
            f" AND (category IN ('{main}') OR category IS NULL)"
        ),
        "music_inbox": one(
            f"SELECT COUNT(*) FROM items WHERE {triageable} AND category IN ('{music}')"
        ),
        "pulled_inbox": one(f"SELECT COUNT(*) FROM items WHERE {pulled_only}"),
        "kept": one("SELECT COUNT(*) FROM items WHERE status = 'kept'"),
        "archived": one("SELECT COUNT(*) FROM items WHERE status = 'archived'"),
        "unavailable": one("SELECT COUNT(*) FROM items WHERE available = 0"),
        "unprepped": one(
            "SELECT COUNT(*) FROM items WHERE status = 'inbox' AND available = 1"
            " AND prep_status = 'pending'"
        ),
        "queued": one("SELECT COUNT(*) FROM items WHERE analysis_status IN ('queued','running')"),
        "prioritized_queued": one(
            "SELECT COUNT(*) FROM items WHERE analysis_status IN ('queued','running') AND priority = 1"
        ),
        "analyzed": one("SELECT COUNT(*) FROM items WHERE analysis_status = 'done'"),
        "untagged": one(
            "SELECT COUNT(*) FROM items WHERE available = 1 AND tag_status = 'pending'"
        ),
        "ready": one(
            "SELECT COUNT(*) FROM items WHERE analysis_status = 'done' AND ready_seen = 0"
            " AND status = 'kept'"
        ),
    }


def dumps(value: object) -> str:
    return json.dumps(value, ensure_ascii=False)
