"""GET /api/offline-pack: everything the phone needs to keep working without the Mac."""

from fastapi.testclient import TestClient

from conftest import add
from test_actions import analyzed
from videomentor.api import create_app
from videomentor.config import Settings


def client():
    c = TestClient(create_app(Settings(pair_code="T"), run_worker=False))
    c.headers["Authorization"] = "Bearer T"
    return c


def test_pack_has_every_part(conn):
    kept = analyzed(conn, "k1", ["Try this"])
    add(conn, "inbox1")
    with client() as c:
        p = c.get("/api/offline-pack").json()
    assert set(p) >= {"generated_at", "library", "ready", "actions", "training", "items", "decks"}
    assert [x["id"] for x in p["library"]["kept"]] == [kept]
    assert p["items"][kept]["analysis"]["try_this_week"] == ["Try this"]
    assert set(p["actions"]) == {"all", "open", "done", "skipped", "counts"}
    assert p["actions"]["counts"]["open"] == 1
    assert p["training"] == {"modules": [], "details": {}}
    assert [x["id"] for x in p["decks"]["main"]] == ["yt:inbox1"]
    assert "yt:inbox1" in p["items"]  # deck cards carry their details for the card back


def test_pack_decks_exclude_given_ids(conn):
    add(conn, "a")
    add(conn, "b")
    with client() as c:
        p = c.get("/api/offline-pack", params={"exclude": "yt:a"}).json()
    assert [x["id"] for x in p["decks"]["main"]] == ["yt:b"]


def test_pack_card_count_is_clamped(conn):
    for i in range(15):
        add(conn, f"v{i:02d}")
    with client() as c:
        assert len(c.get("/api/offline-pack", params={"cards": 0}).json()["decks"]["main"]) == 10
        assert len(c.get("/api/offline-pack", params={"cards": 999}).json()["decks"]["main"]) == 15


def test_pack_needs_sign_in(conn):
    with TestClient(create_app(Settings(pair_code="T"), run_worker=False)) as c:
        assert c.get("/api/offline-pack").status_code == 401
