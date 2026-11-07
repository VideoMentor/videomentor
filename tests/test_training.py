"""Training builder (try/train): gather, LLM module, timestamp validation, storage, export."""

import json

from fastapi.testclient import TestClient

from conftest import add
from videomentor import db, llm, tagging, training, transcripts
from videomentor.api import create_app
from videomentor.config import Settings

LINES = [(t, f"line at {t}") for t in range(0, 600, 10)]


def source(conn, vid, tag="communication skills", signal=4, status="kept"):
    item = add(conn, vid)
    analysis = {
        "core_idea": f"core {vid}",
        "frameworks": [{"name": "F", "how": "use F"}],
        "takeaways": ["t"],
        "moments": [{"t": 120, "label": "the move"}],
        "key_moment": {"t": 120, "label": "the move"},
        "signal": signal,
    }
    conn.execute(
        "UPDATE items SET status = ?, analysis_status = 'done', analysis = ?, duration_s = 600 WHERE id = ?",
        (status, json.dumps(analysis), item),
    )
    tagging.set_tags(conn, item, [tag])
    transcripts.save(conn, item, LINES)
    conn.commit()
    return item


MODULE = {
    "title": "Handle blame calmly",
    "outcome": "Answer blame in one breath",
    "minutes": 30,
    "lessons": [
        {
            "title": "The move",
            "goal": "Spot it",
            "clips": [
                {"video": "yt:a", "start": 118, "end": 200, "why": "shows it", "watch_for": "tone"},
                {"video": "yt:a", "start": 5000, "end": 5100, "why": "made up", "watch_for": "x"},
                {
                    "video": "yt:nope",
                    "start": 10,
                    "end": 50,
                    "why": "not a source",
                    "watch_for": "x",
                },
                {
                    "video": "yt:b",
                    "start": 300,
                    "end": 250,
                    "why": "ends before start",
                    "watch_for": "x",
                },
                {"video": "yt:b", "start": 0, "end": 2000, "why": "too long", "watch_for": "x"},
            ],
            "exercise": "Say it out loud",
        }
    ],
    "quiz": [
        {
            "question": "What lowers the room?",
            "answer": "A falling tone",
            "video": "yt:a",
            "t": 121,
        },
        {"question": "Invented?", "answer": "x", "video": "yt:a", "t": 9999},
    ],
    "gaps": ["salary negotiation"],
}


def test_gather_picks_kept_analyzed_tagged_videos_by_signal(conn):
    source(conn, "a", signal=3)
    source(conn, "b", signal=5)
    source(conn, "c", status="archived")
    source(conn, "d", tag="other")
    got = training.gather(conn, "Communication Skills")
    assert [g["id"] for g in got] == ["yt:b", "yt:a"]
    assert "line at 120" in got[0]["passages"]


def test_build_validates_every_timestamp(conn, monkeypatch):
    source(conn, "a")
    source(conn, "b")
    seen = {}

    def fake(prompt, **kw):
        seen["prompt"] = prompt
        return json.loads(json.dumps(MODULE))

    monkeypatch.setattr(llm, "structured", fake)
    module = training.build(conn, "communication skills", model="sonnet", goal="a meeting Thursday")
    assert "a meeting Thursday" in seen["prompt"] and "yt:a" in seen["prompt"]
    clips = module["lessons"][0]["clips"]
    assert [(c["video"], c["start"], c["end"]) for c in clips] == [("yt:a", 118, 200)]
    assert clips[0]["title"] == "Video a" and clips[0]["url"].endswith("watch?v=a&t=118s")
    assert [q["t"] for q in module["quiz"]] == [121]
    assert module["dropped"] == 5


def test_build_needs_material(conn):
    try:
        training.build(conn, "nothing here", model="sonnet")
    except training.NotEnoughMaterial:
        pass
    else:
        raise AssertionError("expected NotEnoughMaterial")


def test_store_and_markdown(conn, monkeypatch, vm_home):
    source(conn, "a")
    monkeypatch.setattr(llm, "structured", lambda *a, **k: json.loads(json.dumps(MODULE)))
    mid = training.create(conn, "communication skills")
    training.run_build(conn, mid, model="sonnet")
    row = training.get(conn, mid)
    assert row["status"] == "ready" and row["module"]["title"] == "Handle blame calmly"
    md = (vm_home / "training").glob("*.md")
    text = next(md).read_text()
    assert "# Handle blame calmly" in text and "watch?v=a&t=118s" in text and "(to 3:20)" in text


def test_api_builds_in_background(conn, monkeypatch):
    source(conn, "a")
    monkeypatch.setattr(llm, "structured", lambda *a, **k: json.loads(json.dumps(MODULE)))
    monkeypatch.setattr(training, "start_thread", lambda fn: fn())  # run inline in tests
    with TestClient(create_app(Settings(pair_code="T"), run_worker=False)) as c:
        c.headers["Authorization"] = "Bearer T"
        r = c.post("/api/training", json={"tag": "communication skills"}).json()
        got = c.get(f"/api/training/{r['id']}").json()
        assert got["status"] == "ready" and got["module"]["lessons"][0]["clips"]
        assert [m["title"] for m in c.get("/api/training").json()["modules"]] == [
            "Handle blame calmly"
        ]
        assert c.post("/api/training", json={"tag": "nothing here"}).status_code == 422
    assert db.get_item(conn, "yt:a")
