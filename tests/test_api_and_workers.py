import re

import pytest
from fastapi.testclient import TestClient

from conftest import add
from videomentor import analyze, db, llm, prep
from videomentor.api import create_app
from videomentor.config import Settings, load_settings
from videomentor.markdown import item_path
from videomentor.sources import youtube


@pytest.fixture
def client(conn):
    settings = load_settings()
    app = create_app(settings, run_worker=False)
    with TestClient(app) as c:
        c.get(f"/pair?code={settings.pair_code}", follow_redirects=False)
        yield c


def test_api_requires_pairing(conn):
    settings = load_settings()
    with TestClient(create_app(settings, run_worker=False)) as c:
        assert c.get("/api/status").status_code == 401
        assert c.get("/pair?code=WRONG").status_code == 401
        r = c.get(f"/pair?code={settings.pair_code.lower()}", follow_redirects=False)
        assert r.status_code == 303
        assert c.get("/api/status").status_code == 200
    with TestClient(create_app(settings, run_worker=False)) as c:
        headers = {"Authorization": f"Bearer {settings.pair_code}"}
        assert c.get("/api/status", headers=headers).status_code == 200


def test_deck_decide_batch_undo_flow(client, conn):
    a, b = add(conn, "aaaaaaaaaaa", topics=["MCP"]), add(conn, "bbbbbbbbbbb", topics=["MCP"])
    cards = client.get("/api/deck?deck=main&n=10").json()["cards"]
    assert {c["id"] for c in cards} == {a, b}
    assert cards[0]["thumbnail"].startswith("https://i.ytimg.com/vi/")

    r = client.post(
        "/api/decisions/batch",
        json={
            "decisions": [
                {"client_id": "x1", "item_id": a, "action": "keep"},
                {"client_id": "x2", "item_id": "yt:nope", "action": "keep"},
                {"client_id": "x1", "item_id": a, "action": "keep"},
            ]
        },
    ).json()["results"]
    assert [x["ok"] for x in r] == [True, False, True]
    assert r[0]["decision_id"] == r[2]["decision_id"]
    assert item_path("aaaaaaaaaaa").exists()

    assert client.get("/api/deck").json()["cards"][0]["id"] == b
    undo = client.post("/api/undo", json={}).json()
    assert undo["items"][0]["status"] == "inbox"
    assert client.get("/api/status").json()["counts"]["inbox"] == 2


def test_group_endpoints(client, conn):
    a, b = add(conn, "aaaaaaaaaaa", topics=["MCP"]), add(conn, "bbbbbbbbbbb", topics=["MCP"])
    g = client.post("/api/groups", json={"anchor_item_id": a}).json()
    assert [c["id"] for c in g["items"]] == [a, b]
    r = client.post(
        f"/api/groups/{g['group']['id']}/decide", json={"client_id": "g", "action": "archive"}
    )
    assert {c["status"] for c in r.json()["items"]} == {"archived"}
    assert client.post("/api/groups", json={"anchor_item_id": "yt:nope"}).status_code == 404


def test_item_detail_and_library_search(client, conn):
    a = add(conn, "aaaaaaaaaaa")
    client.post("/api/decisions", json={"client_id": "k", "item_id": a, "action": "keep"})
    detail = client.get(f"/api/items/{a}").json()
    assert detail["decisions"][0]["action"] == "keep"
    assert [i["id"] for i in client.get("/api/library?q=Video").json()["items"]] == [a]
    assert client.get("/api/library?q=zzz").json()["items"] == []


def test_prep_batch_writes_cards(conn, monkeypatch):
    library_item = add(conn, "aaaaaaaaaaa")
    conn.execute("UPDATE items SET prep_status = 'pending', enrich_status = 'done'")
    seen = {}

    def fake(prompt, **kw):
        seen["prompt"] = prompt
        return {
            "items": [
                {
                    "id": library_item,
                    "why": "Teaches X",
                    "topics": ["X", "Y", "Z", "W"],
                    "category": "music",
                }
            ]
        }

    monkeypatch.setattr(llm, "structured", fake)
    assert prep.prep_batch(conn, prep.pending(conn, 20), "haiku") == 1
    item = db.get_item(conn, library_item)
    assert (item["why"], item["topics"], item["category"]) == (
        "Teaches X",
        ["X", "Y", "Z"],
        "music",
    )
    assert "Video aaaaaaaaaaa" in seen["prompt"]


def test_prep_failure_retries_then_fails(conn, monkeypatch):
    add(conn, "aaaaaaaaaaa")
    conn.execute("UPDATE items SET prep_status = 'pending', enrich_status = 'done'")

    def boom(*a, **k):
        raise llm.LLMError("down")

    monkeypatch.setattr(llm, "structured", boom)
    for _ in range(prep.MAX_ATTEMPTS):
        with pytest.raises(llm.LLMError):
            prep.prep_batch(conn, prep.pending(conn, 20), "haiku")
    assert db.get_item(conn, "yt:aaaaaaaaaaa")["prep_status"] == "failed"


def test_analysis_queue_order_and_result(conn, monkeypatch):
    from videomentor import library

    kept, prio = add(conn, "aaaaaaaaaaa"), add(conn, "bbbbbbbbbbb")
    library.decide(conn, kept, "keep", "c1")
    library.decide(conn, prio, "prioritize", "c2")
    assert analyze.next_item(conn)["id"] == prio

    monkeypatch.setattr(
        youtube, "fetch_transcript", lambda vid, prof: [(0, "intro"), (40, "main idea")]
    )
    captured = {}

    def fake(prompt, **kw):
        captured["prompt"] = prompt
        return {
            "summary": "Sum",
            "key_points": ["k"],
            "moments": [{"t": 40, "label": "idea"}],
            "learnings": ["l"],
            "curriculum_topic": "Topic",
        }

    monkeypatch.setattr(llm, "structured", fake)
    result = analyze.analyze_item(conn, analyze.next_item(conn), chrome_profile="P", model="sonnet")
    assert result["transcript_source"] == "captions"
    assert "[0:40 = 40s] main idea" in captured["prompt"]
    item = db.get_item(conn, prio)
    assert item["analysis_status"] == "done" and item["analysis"]["summary"] == "Sum"
    md = item_path("bbbbbbbbbbb").read_text()
    assert "## Moments" in md and "&t=40s" in md
    assert analyze.next_item(conn)["id"] == kept


def test_analysis_failure_is_recorded(conn, monkeypatch):
    from videomentor import library

    a = add(conn, "aaaaaaaaaaa")
    library.decide(conn, a, "prioritize", "c1")
    monkeypatch.setattr(youtube, "fetch_transcript", lambda vid, prof: None)
    monkeypatch.setattr(llm, "structured", lambda *a, **k: (_ for _ in ()).throw(llm.LLMError("x")))
    with pytest.raises(llm.LLMError):
        analyze.analyze_item(conn, db.get_item(conn, a), chrome_profile="P", model="sonnet")
    assert db.get_item(conn, a)["analysis_status"] == "failed"


def test_settings_roundtrip(vm_home):
    s = load_settings()
    assert re.fullmatch(r"\d{4}-\d{4}-\d{4}", s.pair_code)
    assert load_settings().pair_code == s.pair_code
    assert isinstance(Settings().bookmark_chrome_profiles, list)
