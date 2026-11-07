"""post time and channel details, tags, touch events, tag history, channel sheet."""

import sqlite3

import pytest
from fastapi.testclient import TestClient

from conftest import add
from videomentor import db, library, llm, sync, tagging
from videomentor.api import create_app
from videomentor.config import Settings
from videomentor.sources import youtube

META = {
    "title": "Pricing talk",
    "channel": "Lenny's Podcast",
    "channel_id": "UC1",
    "duration_s": 3600,
    "description": "about pricing",
    "tags": ["pricing"],
    "yt_categories": ["Education"],
    "upload_date": "20250304",
    "timestamp": 1741097700,
    "channel_handle": "@lennyspodcast",
    "channel_followers": 500000,
    "view_count": 12345,
    "chapters": [],
}


@pytest.fixture
def client(conn):
    app = create_app(Settings(pair_code="TESTCODE"), run_worker=False)
    with TestClient(app) as c:
        c.headers["Authorization"] = "Bearer TESTCODE"
        yield c


# --- byline -----------------------------------------------------------------


def test_enrich_stores_post_time_and_channel_details(conn, monkeypatch):
    add(conn, "v1")
    conn.execute("UPDATE items SET enrich_status = 'pending' WHERE id = 'yt:v1'")
    monkeypatch.setattr(youtube, "fetch_metadata", lambda vid, prof: META)
    sync.enrich_pending(conn, Settings(pair_code="X"))
    item = db.get_item(conn, "yt:v1")
    assert item["posted_ts"] == 1741097700
    assert item["channel_handle"] == "@lennyspodcast"
    assert item["channel_followers"] == 500000
    assert item["view_count"] == 12345


def test_card_posted_at_exact_and_date_only(conn):
    a = add(conn, "v1")
    b = add(conn, "v2")
    conn.execute(
        "UPDATE items SET posted_ts = 1741097700, upload_date = '20250304' WHERE id = ?", (a,)
    )
    conn.execute("UPDATE items SET upload_date = '20240101' WHERE id = ?", (b,))
    ca = library.card(conn, db.get_item(conn, a))
    cb = library.card(conn, db.get_item(conn, b))
    assert ca["posted_at"] == "2025-03-04T14:15:00+00:00" and ca["posted_exact"] is True
    assert cb["posted_at"] == "2024-01-01" and cb["posted_exact"] is False


def test_migration_adds_columns_without_touching_status(tmp_path):
    path = tmp_path / "old.db"
    old = sqlite3.connect(path)
    old.executescript(
        "CREATE TABLE items (id TEXT PRIMARY KEY, video_id TEXT NOT NULL UNIQUE, url TEXT NOT NULL,"
        " title TEXT, channel TEXT, channel_id TEXT, duration_s INTEGER, description TEXT,"
        " tags TEXT NOT NULL DEFAULT '[]', yt_categories TEXT NOT NULL DEFAULT '[]',"
        " upload_date TEXT, chapters TEXT NOT NULL DEFAULT '[]',"
        " available INTEGER NOT NULL DEFAULT 1, added_at TEXT NOT NULL,"
        " added_known INTEGER NOT NULL DEFAULT 0, wl_position INTEGER,"
        " status TEXT NOT NULL DEFAULT 'inbox', status_reason TEXT,"
        " priority INTEGER NOT NULL DEFAULT 0, why TEXT, topics TEXT NOT NULL DEFAULT '[]',"
        " category TEXT, enrich_status TEXT NOT NULL DEFAULT 'pending',"
        " prep_status TEXT NOT NULL DEFAULT 'pending', prep_attempts INTEGER NOT NULL DEFAULT 0,"
        " analysis_status TEXT NOT NULL DEFAULT 'none', analysis TEXT, analysis_error TEXT,"
        " analysis_queued_at TEXT, analyzed_at TEXT, ready_seen INTEGER NOT NULL DEFAULT 0,"
        " created_at TEXT NOT NULL, updated_at TEXT NOT NULL);"
        "INSERT INTO items (id, video_id, url, added_at, created_at, updated_at, enrich_status)"
        " VALUES ('yt:a', 'a', 'u', 't', 't', 't', 'done');"
    )
    old.commit()
    old.close()
    c = db.connect(path)
    db.init(c)
    db.init(c)  # idempotent
    cols = {r["name"] for r in c.execute("PRAGMA table_info(items)")}
    assert {
        "posted_ts",
        "channel_handle",
        "channel_followers",
        "view_count",
        "tag_status",
        "enrich_version",
    } <= cols
    row = c.execute("SELECT enrich_status, enrich_version, tag_status FROM items").fetchone()
    assert tuple(row) == ("done", 1, "pending")


def test_enrich_refreshes_items_from_older_versions(conn, monkeypatch):
    add(conn, "v1")
    add(conn, "v2")
    conn.execute("UPDATE items SET enrich_status = 'done', enrich_version = 1")
    conn.execute("UPDATE items SET enrich_version = ? WHERE id = 'yt:v2'", (sync.ENRICH_VERSION,))
    calls = []

    def fetch(vid, prof):
        calls.append(vid)
        return META

    monkeypatch.setattr(youtube, "fetch_metadata", fetch)
    assert sync.enrich_pending(conn, Settings(pair_code="X")) == 1
    assert calls == ["v1"]
    assert db.get_item(conn, "yt:v1")["posted_ts"] == 1741097700
    assert sync.enrich_pending(conn, Settings(pair_code="X")) == 0


# --- tags -------------------------------------------------------------------


def test_normalize_tags():
    vocab = {"cold outreach": "cold outreach", "claude code": "Claude Code"}
    out = tagging.normalize(
        ["  Cold   Outreach ", "claude code", "", "pricing", "Pricing", "x" * 80, *"abcdefgh"],
        vocab,
    )
    assert out[:3] == ["cold outreach", "Claude Code", "pricing"]
    assert len(out) == tagging.MAX_TAGS
    assert all(len(t) <= tagging.MAX_TAG_LEN for t in out)


def test_tag_batch_reuses_vocabulary_and_marks_done(conn, monkeypatch):
    a = add(conn, "v1")
    b = add(conn, "v2")
    c = add(conn, "v3")
    conn.execute("UPDATE items SET enrich_status = 'done'")
    tagging.set_tags(conn, c, ["Claude Code"])
    conn.execute("UPDATE items SET tag_status = 'done' WHERE id = ?", (c,))
    seen = {}

    def fake(prompt, **kw):
        seen["prompt"] = prompt
        return {"items": [{"id": a, "tags": ["claude code", "agents", "Agents"]}]}

    monkeypatch.setattr(llm, "structured", fake)
    pending = tagging.pending(conn, 10)
    assert {i["id"] for i in pending} == {a, b}
    assert tagging.tag_batch(conn, pending, "haiku") == 1
    assert "Claude Code" in seen["prompt"]
    assert tagging.item_tags(conn, a) == ["Claude Code", "agents"]
    statuses = dict(conn.execute("SELECT id, tag_status FROM items").fetchall())
    assert statuses[a] == "done" and statuses[b] == "failed"


def test_tag_batch_llm_error_leaves_pending(conn, monkeypatch):
    a = add(conn, "v1")
    conn.execute("UPDATE items SET enrich_status = 'done'")

    def boom(*a, **k):
        raise llm.LLMError("down")

    monkeypatch.setattr(llm, "structured", boom)
    with pytest.raises(llm.LLMError):
        tagging.tag_batch(conn, tagging.pending(conn, 10), "haiku")
    assert db.get_item(conn, a)["tag_status"] == "pending"


def test_card_has_tags_and_library_searches_them(conn):
    a = add(conn, "v1")
    add(conn, "v2")
    tagging.set_tags(conn, a, ["negotiation tactics", "sales"])
    conn.execute("UPDATE items SET status = 'kept'")
    assert library.card(conn, db.get_item(conn, a))["tags"] == ["negotiation tactics", "sales"]
    hits = library.library_items(conn, "kept", "negotiation")
    assert [h["id"] for h in hits] == [a]


# --- events and tag history -------------------------------------------------


def test_events_are_idempotent(client, conn):
    a = add(conn, "v1")
    body = {
        "events": [{"client_id": "e1", "item_id": a, "kind": "flip", "at": "2026-10-31T10:00:00Z"}]
    }
    assert client.post("/api/events", json=body).json() == {"stored": 1}
    assert client.post("/api/events", json=body).json() == {"stored": 0}
    bad = {"events": [{"client_id": "e2", "item_id": "yt:nope", "kind": "flip"}]}
    assert client.post("/api/events", json=bad).json() == {"stored": 0}
    assert (
        client.post(
            "/api/events", json={"events": [{"client_id": "e3", "item_id": a, "kind": "x"}]}
        ).status_code
        == 422
    )


def test_tag_history_lists_touched_items_newest_first(client, conn):
    kept = add(conn, "v1")
    flipped = add(conn, "v2")
    untouched = add(conn, "v3")
    auto = add(conn, "v4")
    for i in (kept, flipped, untouched, auto):
        tagging.set_tags(conn, i, ["pricing"])
    tagging.set_tags(conn, kept, ["pricing", "saas"])
    conn.commit()
    client.post(
        "/api/decisions",
        json={"client_id": "d1", "item_id": kept, "action": "keep", "at": "2026-10-31T09:00:00Z"},
    )
    client.post(
        "/api/events",
        json={
            "events": [
                {
                    "client_id": "e1",
                    "item_id": flipped,
                    "kind": "flip",
                    "at": "2026-10-31T11:00:00Z",
                }
            ]
        },
    )
    library.mark_unavailable(conn, auto)
    conn.commit()

    r = client.get("/api/tags/Pricing/history").json()
    assert r["tag"] == "pricing"
    assert r["total"] == 4
    assert [i["id"] for i in r["items"]] == [flipped, kept]
    assert r["items"][0]["last_action"] == "flip"
    assert r["items"][1]["last_action"] == "keep"
    assert r["related"] == [{"tag": "saas", "count": 1}]
    assert client.get("/api/tags/unknown/history").json()["total"] == 0


def test_channel_sheet_counts(client, conn):
    a = add(conn, "v1", channel="Lenny")
    add(conn, "v2", channel="Lenny")
    add(conn, "v3", channel="Other")
    conn.execute(
        "UPDATE items SET channel_id = 'UC1', channel_handle = '@lenny', channel_followers = 9 WHERE channel = 'Lenny'"
    )
    conn.execute("UPDATE items SET status = 'kept' WHERE id = ?", (a,))
    conn.commit()
    r = client.get("/api/channel", params={"channel_id": "UC1"}).json()
    assert r["channel"] == "Lenny" and r["handle"] == "@lenny" and r["followers"] == 9
    assert r["counts"] == {"saved": 2, "kept": 1, "archived": 0, "inbox": 1}
    by_name = client.get("/api/channel", params={"name": "Other"}).json()
    assert by_name["counts"]["saved"] == 1
    assert client.get("/api/channel", params={"name": "Nobody"}).status_code == 404


def test_item_detail_has_info_fields(client, conn):
    a = add(conn, "v1")
    conn.execute(
        "UPDATE items SET channel_handle = '@c', view_count = 7, tags = '[\"yt\"]',"
        " yt_categories = '[\"Education\"]' WHERE id = ?",
        (a,),
    )
    tagging.set_tags(conn, a, ["pricing"])
    conn.commit()
    d = client.get(f"/api/items/{a}").json()
    assert d["channel_handle"] == "@c" and d["view_count"] == 7
    assert d["yt_tags"] == ["yt"] and d["yt_categories"] == ["Education"]
    assert d["tags"] == ["pricing"]
    assert [s["source"] for s in d["saved_in"]] == ["youtube:watch_later"]


def test_library_processed_includes_kept_and_archived_with_decided_at(client, conn):
    k = add(conn, "k1")
    a = add(conn, "a1")
    gone = add(conn, "g1")
    add(conn, "i1")  # still in the deck
    client.post(
        "/api/decisions",
        json={"client_id": "d1", "item_id": k, "action": "keep", "at": "2026-10-30T10:00:00Z"},
    )
    client.post(
        "/api/decisions",
        json={"client_id": "d2", "item_id": a, "action": "archive", "at": "2026-10-31T10:00:00Z"},
    )
    library.mark_unavailable(conn, gone)  # automatic archive: not your decision
    conn.commit()
    items = client.get("/api/library", params={"status": "processed"}).json()["items"]
    assert {i["id"]: i["decided_at"] for i in items} == {
        k: "2026-10-30T10:00:00Z",
        a: "2026-10-31T10:00:00Z",
    }
    kept = client.get("/api/library", params={"status": "kept"}).json()["items"]
    assert [i["id"] for i in kept] == [k]


def test_ready_rows_carry_decided_and_analyzed_times(client, conn):
    k = add(conn, "k1")
    client.post(
        "/api/decisions",
        json={"client_id": "d1", "item_id": k, "action": "keep", "at": "2026-10-30T10:00:00Z"},
    )
    conn.execute(
        "UPDATE items SET analysis_status = 'done', analyzed_at = '2026-10-31T09:00:00+00:00' WHERE id = ?",
        (k,),
    )
    conn.commit()
    (row,) = client.get("/api/ready").json()["items"]
    assert row["decided_at"] == "2026-10-30T10:00:00Z"
    assert row["analyzed_at"] == "2026-10-31T09:00:00+00:00"
