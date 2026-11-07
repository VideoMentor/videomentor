"""Tag merge list: LLM draft, validation, approve and apply, undo, aliases for future tagging."""

import pytest
from fastapi.testclient import TestClient

from conftest import add
from videomentor import db, llm, tag_merge, tagging
from videomentor.api import create_app
from videomentor.config import Settings


@pytest.fixture
def tagged(conn):
    a, b, c = add(conn, "a"), add(conn, "b"), add(conn, "c")
    tagging.set_tags(conn, a, ["communication skills", "workplace communication"])
    tagging.set_tags(conn, b, ["workplace communication", "pricing", "communication skills"])
    tagging.set_tags(conn, c, ["communication skill", "Pricing strategy", "sales"])
    conn.commit()
    return a, b, c


def test_validate_drops_bad_proposals(tagged, conn):
    raw = [
        {
            "keep": "communication skills",
            "fold": ["workplace communication", "communication skill", "nope"],
            "reason": "same",
        },
        {
            "keep": "pricing",
            "fold": ["workplace communication"],
            "reason": "dup fold",
        },  # already folded
        {"keep": "sales", "fold": ["sales"], "reason": "self"},
        {"keep": "missing", "fold": ["pricing"], "reason": "unknown keep"},
        {"keep": "pricing", "fold": ["Pricing Strategy"], "reason": "case-insensitive match"},
        {"keep": "sales", "fold": ["communication skills"], "reason": "backwards: fold used more"},
        {"keep": "pricing strategy", "fold": ["sales"], "reason": "keep already folded"},
    ]
    out = tag_merge.validate(raw, {t: n for t, n in tagging.vocabulary(conn)})
    assert out == [
        {
            "keep": "communication skills",
            "fold": ["workplace communication", "communication skill"],
            "reason": "same",
        },
        {"keep": "pricing", "fold": ["Pricing strategy"], "reason": "case-insensitive match"},
    ]


def test_draft_stores_proposals_and_replaces_old_ones(tagged, conn, monkeypatch):
    seen = {}

    def fake(prompt, **kw):
        seen["prompt"] = prompt
        return {"merges": [{"keep": "pricing", "fold": ["Pricing strategy"], "reason": "variant"}]}

    monkeypatch.setattr(llm, "structured", fake)
    assert tag_merge.draft(conn, "sonnet") == 1
    assert "workplace communication (2)" in seen["prompt"]
    assert tag_merge.draft(conn, "sonnet") == 1  # a new draft replaces unreviewed proposals
    rows = tag_merge.list_merges(conn)
    assert [(r["keep"], r["fold"], r["status"]) for r in rows] == [
        ("pricing", ["Pricing strategy"], "proposed")
    ]
    assert rows[0]["videos"] == 1


def test_apply_and_undo(tagged, conn):
    a, b, c = tagged
    tag_merge.save_proposals(
        conn,
        [
            {
                "keep": "communication skills",
                "fold": ["workplace communication", "communication skill"],
                "reason": "",
            },
            {"keep": "pricing", "fold": ["Pricing strategy"], "reason": ""},
        ],
    )
    first, second = tag_merge.list_merges(conn)
    out = tag_merge.apply(conn, approve=[first["id"]], reject=[second["id"]])
    assert out == {"applied": 1, "rejected": 1, "videos": 3}
    assert tagging.item_tags(conn, a) == ["communication skills"]
    assert tagging.item_tags(conn, b) == ["pricing", "communication skills"]
    assert out["videos"] == 3
    assert tagging.item_tags(conn, c) == ["Pricing strategy", "sales", "communication skills"]
    assert dict(tagging.vocabulary(conn))["communication skills"] == 3
    assert "workplace communication" not in dict(tagging.vocabulary(conn))
    # future tagging maps the folded names to the kept one
    vocab = tagging.vocab_map(conn)
    assert tagging.normalize(["Workplace Communication", "new tag"], vocab) == [
        "communication skills",
        "new tag",
    ]
    # undo restores exactly what was there
    tag_merge.undo(conn, first["id"])
    assert sorted(tagging.item_tags(conn, a)) == ["communication skills", "workplace communication"]
    assert sorted(tagging.item_tags(conn, c)) == [
        "Pricing strategy",
        "communication skill",
        "sales",
    ]
    assert tag_merge.list_merges(conn)[0]["status"] == "undone"


def test_api(tagged, conn):
    tag_merge.save_proposals(
        conn, [{"keep": "pricing", "fold": ["Pricing strategy"], "reason": "variant"}]
    )
    app = create_app(Settings(pair_code="T"), run_worker=False)
    with TestClient(app) as c:
        c.headers["Authorization"] = "Bearer T"
        r = c.get("/api/tag-merges").json()
        assert r["counts"] == {"proposed": 1, "applied": 0} and r["merges"][0]["keep"] == "pricing"
        mid = r["merges"][0]["id"]
        assert (
            c.post("/api/tag-merges/apply", json={"approve": [mid], "reject": []}).json()["applied"]
            == 1
        )
        assert c.get("/api/tag-merges").json()["counts"] == {"proposed": 0, "applied": 1}
        assert c.post(f"/api/tag-merges/{mid}/undo").json()["status"] == "undone"
        assert c.post("/api/tag-merges/999/undo").status_code == 404
    assert db.get_item(conn, tagged[2])
