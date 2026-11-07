"""Transcripts kept after analysis; tags feed the analysis and the Markdown export."""

from conftest import add
from videomentor import analyze, db, llm, markdown, tagging, transcripts
from videomentor.sources import youtube

LINES = [(0, "Welcome"), (12, "first we price"), (45, "then we negotiate"), (3700, "the end")]
RESULT = {
    "summary": "s",
    "key_points": ["k"],
    "moments": [{"t": 12, "label": "pricing", "tag": "pricing"}],
    "learnings": ["l"],
    "curriculum_topic": "Sales",
}


def test_analysis_keeps_transcript_and_sees_tags(conn, monkeypatch):
    a = add(conn, "v1")
    tagging.set_tags(conn, a, ["pricing", "negotiation tactics"])
    conn.commit()
    seen = {}
    monkeypatch.setattr(youtube, "fetch_transcript", lambda vid, prof: LINES)

    def fake(prompt, **kw):
        seen["prompt"], seen["schema"] = prompt, kw["schema"]
        return dict(RESULT)

    monkeypatch.setattr(llm, "structured", fake)
    analyze.analyze_item(conn, db.get_item(conn, a), chrome_profile="P", model="m")
    assert "Tags: pricing, negotiation tactics" in seen["prompt"]
    assert "tag" in seen["schema"]["properties"]["moments"]["items"]["properties"]
    t = transcripts.get(conn, a)
    assert t["source"] == "captions" and t["lines"][1] == [12, "first we price"]


def test_no_captions_is_remembered(conn, monkeypatch):
    a = add(conn, "v1")
    monkeypatch.setattr(youtube, "fetch_transcript", lambda vid, prof: None)
    monkeypatch.setattr(llm, "structured", lambda *a, **k: dict(RESULT))
    analyze.analyze_item(conn, db.get_item(conn, a), chrome_profile="P", model="m")
    assert transcripts.get(conn, a)["source"] == "none"


def test_backfill_fetches_only_analyzed_items_without_transcripts(conn, monkeypatch):
    a = add(conn, "v1")
    b = add(conn, "v2")
    add(conn, "v3")  # not analyzed: skipped
    conn.execute("UPDATE items SET analysis_status = 'done' WHERE id IN (?, ?)", (a, b))
    transcripts.save(conn, b, LINES)
    calls = []

    def fetch(vid, prof):
        calls.append(vid)
        return LINES

    monkeypatch.setattr(youtube, "fetch_transcript", fetch)
    assert transcripts.fetch_missing(conn, "P") == {"fetched": 1, "no_captions": 0, "failed": 0}
    assert calls == ["v1"]
    assert transcripts.fetch_missing(conn, "P")["fetched"] == 0


def test_markdown_has_tags_and_transcript_file(conn):
    a = add(conn, "v1")
    tagging.set_tags(conn, a, ["pricing"])
    conn.execute(
        "UPDATE items SET analysis = ?, analysis_status = 'done', posted_ts = 1741097700 WHERE id = ?",
        (library_dumps(RESULT), a),
    )
    transcripts.save(conn, a, LINES)
    path = markdown.write_item(conn, a)
    text = path.read_text()
    assert 'tags: ["pricing"]' in text
    assert 'posted_at: "2025-03-04T14:15:00+00:00"' in text
    assert "[12s] pricing" not in text  # moments keep their old format
    assert "Transcript: [v1.transcript.md](v1.transcript.md)" in text
    tx = markdown.transcript_path("v1").read_text()
    assert "[0:00] Welcome first we price" in tx
    assert "[0:45] then we negotiate" in tx
    assert "[1:01:40] the end" in tx
    assert "https://www.youtube.com/watch?v=v1" in tx


def library_dumps(v):
    from videomentor.library import dumps

    return dumps(v)
