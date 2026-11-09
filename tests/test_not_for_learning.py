"""Not for learning: the music and entertainment deck source, and the bulk archive with Undo."""

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from conftest import add
from videomentor import library
from videomentor.api import create_app
from videomentor.config import Settings


def client():
    c = TestClient(create_app(Settings(pair_code="T"), run_worker=False))
    c.headers["Authorization"] = "Bearer T"
    return c


def days_ago(n: int) -> str:
    return (datetime.now(UTC) - timedelta(days=n)).strftime("%Y-%m-%d")


def seed(conn):
    ids = {
        "music_old": add(conn, "mmmmmmmmmm1", category="music", added=days_ago(40)),
        "ent_old": add(conn, "mmmmmmmmmm2", category="entertainment", added=days_ago(40)),
        "music_new": add(conn, "mmmmmmmmmm3", category="music", added=days_ago(5)),
        "music_kept": add(conn, "mmmmmmmmmm4", category="music", added=days_ago(40)),
        "learn_old": add(conn, "mmmmmmmmmm5", category="learning", added=days_ago(40)),
    }
    library.decide(conn, ids["music_kept"], "keep", "k1")
    conn.commit()
    return ids


def status(conn, item_id):
    return conn.execute("SELECT status FROM items WHERE id = ?", (item_id,)).fetchone()[0]


def test_nl_source_deals_music_and_entertainment_only(conn):
    ids = seed(conn)
    got = {c["id"] for c in library.deck(conn, "main", 10, [], "nl")}
    assert got == {ids["music_old"], ids["ent_old"], ids["music_new"]}
    with client() as c:
        r = c.get("/api/deck", params={"deck": "main", "source": "nl"}).json()
        assert {x["id"] for x in r["cards"]} == got
        legacy = c.get("/api/deck", params={"deck": "music"}).json()
        assert {x["id"] for x in legacy["cards"]} == got


def test_archive_scope(conn):
    ids = seed(conn)
    out = library.archive_not_for_learning(conn)
    assert out["archived"] == 2
    assert out["batch"].startswith("nl-")
    assert status(conn, ids["music_old"]) == "archived"
    assert status(conn, ids["ent_old"]) == "archived"
    assert status(conn, ids["music_new"]) == "inbox"
    assert status(conn, ids["music_kept"]) == "kept"
    assert status(conn, ids["learn_old"]) == "inbox"
    reasons = conn.execute(
        "SELECT DISTINCT reason, batch FROM decisions WHERE batch = ?", (out["batch"],)
    ).fetchall()
    assert [(r["reason"], r["batch"]) for r in reasons] == [("not for learning", out["batch"])]


def test_archive_undo_restores_exactly(conn):
    ids = seed(conn)
    before = {k: status(conn, v) for k, v in ids.items()}
    out = library.archive_not_for_learning(conn)
    conn.commit()
    with client() as c:
        r = c.post("/api/undo-batch", json={"batch": out["batch"]})
        assert r.status_code == 200
        assert r.json() == {"undone": 2, "skipped": 0}
        assert c.post("/api/undo-batch", json={"batch": out["batch"]}).json()["undone"] == 0
        assert c.post("/api/undo-batch", json={"batch": "nl-none"}).json()["undone"] == 0
    assert {k: status(conn, v) for k, v in ids.items()} == before


def test_counts_endpoint(conn):
    seed(conn)
    with client() as c:
        assert c.get("/api/not-for-learning").json() == {"inbox": 3, "older": 2}
        r = c.post("/api/not-for-learning/archive", json={"older_than_days": 30}).json()
        assert r["archived"] == 2
        assert r["batch"].startswith("nl-")
        assert c.get("/api/not-for-learning").json() == {"inbox": 1, "older": 0}


def test_offline_pack_deals_the_nl_source(conn):
    ids = seed(conn)
    with client() as c:
        p = c.get("/api/offline-pack", params={"source": "nl"}).json()
    assert {x["id"] for x in p["decks"]["main"]} == {
        ids["music_old"],
        ids["ent_old"],
        ids["music_new"],
    }


def test_undo_batch_is_partial_when_one_was_decided_again(conn):
    ids = seed(conn)
    out = library.archive_not_for_learning(conn)
    library.decide(conn, ids["ent_old"], "keep", "later")
    conn.commit()
    with client() as c:
        r = c.post("/api/undo-batch", json={"batch": out["batch"]})
    assert r.status_code == 200
    assert r.json() == {"undone": 1, "skipped": 1}
    assert status(conn, ids["music_old"]) == "inbox"
    assert status(conn, ids["ent_old"]) == "kept"


def test_nl_scope_is_saves_only_and_available(conn):
    ids = seed(conn)
    pulled = add(conn, "mmmmmmmmmm6", category="music", added=days_ago(40))
    conn.execute("DELETE FROM item_sources WHERE item_id = ?", (pulled,))
    conn.execute(
        "INSERT INTO item_sources (item_id, source, first_seen) VALUES (?, 'channel:UCx', '2026-01-01')",
        (pulled,),
    )
    gone = add(conn, "mmmmmmmmmm7", category="music", added=days_ago(40))
    conn.execute("UPDATE items SET available = 0 WHERE id = ?", (gone,))
    conn.commit()
    dealt = {c["id"] for c in library.deck(conn, "main", 20, [], "nl")}
    assert pulled not in dealt and gone not in dealt
    counts = library.not_for_learning_counts(conn)
    assert counts == {"inbox": len(dealt), "older": 2}
    out = library.archive_not_for_learning(conn)
    assert out["archived"] == counts["older"]
    assert status(conn, pulled) == "inbox"
    assert status(conn, gone) == "inbox"
    assert status(conn, ids["music_old"]) == "archived"
