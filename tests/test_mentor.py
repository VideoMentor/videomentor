"""signal score before analysis, business-lens analysis, upgrades, export."""

import json

import pytest
from fastapi.testclient import TestClient

from conftest import add
from videomentor import analyze, db, library, llm, markdown, scoring
from videomentor.api import create_app
from videomentor.config import Settings, load_settings
from videomentor.sources import youtube

SKILLS = Settings().skill_map

V2 = {
    "core_idea": "Anchor first, then concede slowly.",
    "summary": "A talk on negotiation.",
    "key_points": ["Anchor high"],
    "frameworks": [{"name": "Anchoring", "how": "State a number first"}],
    "takeaways": ["Prepare your anchor"],
    "try_this_week": ["Open your next pricing call with a number"],
    "moments": [{"t": 12, "label": "the anchor", "tag": "pricing"}],
    "key_moment": {"t": 12, "label": "the anchor"},
    "skills": ["Negotiation", "Sales", "Juggling"],
    "useful_for": "Anyone pricing services",
    "signal": 5,
    "signal_reason": "Concrete and practical",
    "learnings": ["Anchor first"],
    "curriculum_topic": "Negotiation",
}


def test_skill_map_default_and_editable(vm_home):
    assert "Negotiation" in SKILLS and "AI and tech" in SKILLS
    (vm_home).mkdir(parents=True, exist_ok=True)
    (vm_home / "config.toml").write_text('pair_code = "X"\nskill_map = ["Sales", "Hiring"]\n')
    assert load_settings().skill_map == ["Sales", "Hiring"]


def test_scoring_pass(conn, monkeypatch):
    a = add(conn, "v1")
    b = add(conn, "v2")
    conn.execute("UPDATE items SET enrich_status = 'done'")
    seen = {}

    def fake(prompt, **kw):
        seen["system"] = kw["system"]
        return {"items": [{"id": a, "signal": 9, "reason": "x" * 300}]}

    monkeypatch.setattr(llm, "structured", fake)
    rules = scoring.rules(["Health and wellbeing", "Relationships"], "Any area of life counts.")
    assert scoring.score_batch(conn, scoring.pending(conn, 10), "haiku", rules) == 1
    assert "Health and wellbeing" in seen["system"] and "Any area of life counts." in seen["system"]
    item = db.get_item(conn, a)
    assert item["signal"] == 5  # clamped to 1..5
    assert len(item["signal_reason"]) <= scoring.MAX_REASON
    assert item["signal_source"] == "prep"
    assert db.get_item(conn, b)["signal_status"] == "failed"
    card = library.card(conn, item)
    assert card["signal"] == 5 and card["signal_reason"]


def test_business_analysis_sets_signal_and_key_moment(conn, monkeypatch):
    a = add(conn, "v1")
    conn.execute("UPDATE items SET signal = 2, signal_source = 'prep' WHERE id = ?", (a,))
    monkeypatch.setattr(youtube, "fetch_transcript", lambda vid, prof: [(0, "hi"), (12, "anchor")])
    seen = {}

    def fake(prompt, **kw):
        seen["system"], seen["schema"] = kw["system"], kw["schema"]
        return json.loads(json.dumps(V2))

    monkeypatch.setattr(llm, "structured", fake)
    result = analyze.analyze_item(
        conn, db.get_item(conn, a), chrome_profile="P", model="m", skills=SKILLS
    )
    assert result["version"] == analyze.ANALYSIS_VERSION
    assert result["skills"] == ["Negotiation", "Sales"]  # off-map skills dropped
    assert "try_this_week" in seen["schema"]["required"]
    assert "business" in seen["system"].lower()
    item = db.get_item(conn, a)
    assert item["signal"] == 5 and item["signal_source"] == "analysis"
    card = library.card(conn, item)
    assert card["key_moment"] == {"t": 12, "label": "the anchor"}
    assert card["skills"] == ["Negotiation", "Sales"]


def test_key_moment_dropped_when_not_in_transcript(conn, monkeypatch):
    a = add(conn, "v1")
    monkeypatch.setattr(youtube, "fetch_transcript", lambda vid, prof: [(0, "hi"), (12, "anchor")])
    bad = json.loads(json.dumps(V2)) | {"key_moment": {"t": 9999, "label": "made up"}}
    monkeypatch.setattr(llm, "structured", lambda *a, **k: bad)
    result = analyze.analyze_item(
        conn, db.get_item(conn, a), chrome_profile="P", model="m", skills=SKILLS
    )
    assert result["key_moment"] is None


def test_queue_upgrades_requeues_old_analyses(conn):
    old = add(conn, "v1")
    new = add(conn, "v2")
    add(conn, "v3")
    conn.execute(
        "UPDATE items SET status = 'kept', analysis_status = 'done', analysis = ? WHERE id = ?",
        (json.dumps({"summary": "old"}), old),
    )
    conn.execute(
        "UPDATE items SET status = 'kept', analysis_status = 'done', analysis = ? WHERE id = ?",
        (json.dumps(V2 | {"version": analyze.ANALYSIS_VERSION}), new),
    )
    assert analyze.queue_upgrades(conn) == 1
    assert db.get_item(conn, old)["analysis_status"] == "queued"
    assert db.get_item(conn, new)["analysis_status"] == "done"


def test_markdown_has_business_sections(conn):
    a = add(conn, "v1")
    conn.execute(
        "UPDATE items SET analysis = ?, analysis_status = 'done', signal = 5 WHERE id = ?",
        (json.dumps(V2 | {"version": 2, "skills": ["Negotiation"]}), a),
    )
    text = markdown.write_item(conn, a).read_text()
    for needle in (
        "## Core idea",
        "Anchor first, then concede slowly.",
        "## Frameworks",
        "**Anchoring**: State a number first",
        "## Try this week",
        "- [ ] Open your next pricing call with a number",
        'skills: ["Negotiation"]',
        "signal: 5",
        "Useful for: Anyone pricing services",
    ):
        assert needle in text, needle


@pytest.mark.parametrize(
    "value,expected", [(0, 1), (3, 3), (7, 5), ("4", 4), ("x", None), (None, None)]
)
def test_clamp_signal(value, expected):
    assert scoring.clamp(value) == expected


def test_default_signal_settings_cover_life_not_just_business():
    s = Settings()
    assert "Health and wellbeing" in s.signal_areas and "Business and career" in s.signal_areas
    assert "any area of life" in s.signal_guidance.lower()


def test_signal_settings_api_and_rescore(conn, vm_home):
    a = add(conn, "v1")
    b = add(conn, "v2")
    conn.execute(
        "UPDATE items SET signal = 3, signal_source = 'prep', signal_status = 'done' WHERE id = ?",
        (a,),
    )
    conn.execute(
        "UPDATE items SET signal = 5, signal_source = 'analysis', signal_status = 'done' WHERE id = ?",
        (b,),
    )
    conn.commit()
    # A real 12-digit code: load_settings() below would replace an old-style one.
    settings = Settings(pair_code="1234-5678-9012")
    with TestClient(create_app(settings, run_worker=False)) as c:
        c.headers["Authorization"] = "Bearer 1234-5678-9012"
        r = c.get("/api/settings").json()
        assert r["signal_areas"] == settings.signal_areas and r["skill_map"] == settings.skill_map
        body = {
            "signal_areas": [" Parenting ", "Health", ""],
            "signal_guidance": "Be strict.",
            "skill_map": ["Sales"],
        }
        r = c.put("/api/settings", json=body).json()
        assert r["signal_areas"] == ["Parenting", "Health"] and r["skill_map"] == ["Sales"]
        assert settings.signal_guidance == "Be strict."  # the running app uses it right away
        assert load_settings().signal_areas == ["Parenting", "Health"]  # and it's saved
        assert c.put("/api/settings", json=body | {"signal_guidance": " "}).status_code == 422
        assert c.post("/api/signal/rescore").json() == {"queued": 1}
    assert db.get_item(conn, a)["signal_status"] == "pending"
    assert db.get_item(conn, b)["signal_status"] == "done"  # analysis scores stay until re-analysis
