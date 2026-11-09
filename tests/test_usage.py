"""LLM call tracking (llm_calls), `vm stats`, and the signal saved on decisions."""

import json
import subprocess
from datetime import UTC, datetime, timedelta

import pytest

from conftest import add
from videomentor import cli, db, library, llm, usage

RESULT = {
    "type": "result",
    "is_error": False,
    "duration_ms": 5200,
    "duration_api_ms": 4900,
    "total_cost_usd": 0.0123,
    "usage": {
        "input_tokens": 1200,
        "output_tokens": 300,
        "cache_read_input_tokens": 4000,
        "cache_creation_input_tokens": 500,
    },
    "modelUsage": {"claude-haiku-4-5": {"costUSD": 0.0123}},
    "structured_output": {"items": []},
}


def fake_run(monkeypatch, *, stdout="", returncode=0, exc=None):
    monkeypatch.setattr(llm, "claude_binary", lambda: "/bin/claude")

    def run(cmd, **kw):
        if exc:
            raise exc
        return subprocess.CompletedProcess(cmd, returncode, stdout=stdout, stderr="err")

    monkeypatch.setattr(llm.subprocess, "run", run)


def capture(monkeypatch):
    rows = []
    monkeypatch.setattr(llm, "_recorder", rows.append)
    return rows


def call(**kw):
    return llm.structured("hello", system="SYS", schema={"type": "object"}, model="haiku", **kw)


def test_success_records_usage_without_prompt_text(monkeypatch):
    fake_run(monkeypatch, stdout=json.dumps([{"type": "system"}, RESULT]))
    rows = capture(monkeypatch)
    assert call(step="prep") == {"items": []}
    (r,) = rows
    assert r["step"] == "prep" and r["ok"] == 1 and r["error_kind"] is None
    assert r["item_id"] is None
    assert (r["input_tokens"], r["output_tokens"]) == (1200, 300)
    assert (r["cache_read_tokens"], r["cache_creation_tokens"]) == (4000, 500)
    assert r["cost_usd"] == 0.0123
    assert (r["duration_ms"], r["duration_api_ms"]) == (5200, 4900)
    assert r["model"] == "claude-haiku-4-5"
    assert len(r["prompt_hash"]) == 16
    assert r["prompt_chars"] == len("SYS") + len("hello")
    assert "hello" not in json.dumps(r) and "SYS" not in json.dumps(r)


def test_prompt_hash_follows_system_and_schema(monkeypatch):
    fake_run(monkeypatch, stdout=json.dumps(RESULT))
    rows = capture(monkeypatch)
    call(step="prep")
    llm.structured("other text", system="SYS", schema={"type": "object"}, model="haiku", step="x")
    llm.structured("hello", system="SYS2", schema={"type": "object"}, model="haiku", step="x")
    assert rows[0]["prompt_hash"] == rows[1]["prompt_hash"] != rows[2]["prompt_hash"]


def test_missing_usage_fields_are_null(monkeypatch):
    fake_run(monkeypatch, stdout=json.dumps({"structured_output": {"a": 1}}))
    rows = capture(monkeypatch)
    call(step="analyze", item_id="yt:x")
    r = rows[0]
    assert r["item_id"] == "yt:x" and r["ok"] == 1
    assert r["input_tokens"] is None and r["cost_usd"] is None and r["duration_ms"] is None
    assert r["model"] == "haiku"  # the model asked for, when the result doesn't say


@pytest.mark.parametrize(
    ("setup", "kind"),
    [
        ({"exc": subprocess.TimeoutExpired("claude", 1)}, "timeout"),
        ({"returncode": 1, "stdout": "boom"}, "exit"),
        ({"stdout": "not json"}, "unparseable"),
        ({"stdout": json.dumps(RESULT | {"structured_output": None, "result": "hi"})}, "no_output"),
        ({"stdout": json.dumps(RESULT | {"is_error": True, "result": "bad"})}, "is_error"),
    ],
)
def test_failures_are_recorded_with_kind(monkeypatch, setup, kind):
    fake_run(monkeypatch, **setup)
    rows = capture(monkeypatch)
    with pytest.raises(llm.LLMError):
        call(step="tagging")
    assert rows[0]["ok"] == 0 and rows[0]["error_kind"] == kind and rows[0]["step"] == "tagging"


def test_usage_kept_on_is_error(monkeypatch):
    fake_run(monkeypatch, stdout=json.dumps(RESULT | {"is_error": True}))
    rows = capture(monkeypatch)
    with pytest.raises(llm.LLMError):
        call(step="scoring")
    assert rows[0]["output_tokens"] == 300


def test_recorder_failure_never_breaks_the_call(monkeypatch):
    fake_run(monkeypatch, stdout=json.dumps(RESULT))

    def broken(row):
        raise RuntimeError("disk full")

    monkeypatch.setattr(llm, "_recorder", broken)
    assert call(step="prep") == {"items": []}


def test_install_writes_rows_to_the_library(conn, monkeypatch):
    fake_run(monkeypatch, stdout=json.dumps(RESULT))
    usage.install()
    try:
        call(step="training")
    finally:
        llm.set_recorder(None)
    row = conn.execute("SELECT * FROM llm_calls").fetchone()
    assert row["step"] == "training" and row["output_tokens"] == 300 and row["ok"] == 1
    assert row["at"]


def test_install_prunes_old_rows(conn):
    old = (datetime.now(UTC) - timedelta(days=200)).isoformat(timespec="seconds")
    recent = (datetime.now(UTC) - timedelta(days=10)).isoformat(timespec="seconds")
    for at in (old, recent):
        conn.execute("INSERT INTO llm_calls (at, step, ok) VALUES (?, 'prep', 1)", (at,))
    conn.commit()
    usage.install()
    llm.set_recorder(None)
    assert [r["at"] for r in conn.execute("SELECT at FROM llm_calls")] == [recent]


def seed_calls(conn):
    now = datetime.now(UTC)
    rows = [
        (now - timedelta(days=1), "prep", 1, 100, 10, 0.01),
        (now - timedelta(days=2), "prep", 0, None, None, None),
        (now - timedelta(days=30), "analyze", 1, 1000, 200, 0.2),
    ]
    for at, step, ok, i, o, cost in rows:
        conn.execute(
            "INSERT INTO llm_calls (at, step, ok, input_tokens, output_tokens, cost_usd)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (at.isoformat(timespec="seconds"), step, ok, i, o, cost),
        )
    conn.commit()


def test_summary_totals_and_by_step(conn):
    seed_calls(conn)
    s = usage.summary(conn)
    assert s["total"]["calls"] == 3 and s["total"]["failed"] == 1
    assert s["total"]["input_tokens"] == 1100 and s["total"]["cost_usd"] == pytest.approx(0.21)
    assert s["last_7d"]["calls"] == 2 and s["last_7d"]["cost_usd"] == pytest.approx(0.01)
    steps = {r["step"]: r for r in s["by_step"]}
    assert steps["prep"]["calls"] == 2 and steps["prep"]["failed"] == 1
    assert set(steps["prep"]) == {
        "step",
        "calls",
        "failed",
        "input_tokens",
        "output_tokens",
        "cache_read_tokens",
        "cache_creation_tokens",
        "cost_usd",
    }
    assert s["since"] is not None


def test_summary_empty(conn):
    s = usage.summary(conn)
    assert s["since"] is None and s["total"]["calls"] == 0 and s["by_step"] == []


def test_vm_stats_prints_by_step(conn, capsys):
    seed_calls(conn)
    cli.main(["stats"])
    out = capsys.readouterr().out
    assert "prep" in out and "analyze" in out
    assert "All time" in out and "Last 7 days" in out
    assert "billed to your Anthropic account" in out
    assert "count toward your Claude plan's usage limits" in out
    assert "not billed on Pro or Max" not in out
    assert "—" not in out


def test_usage_is_split_by_backend(conn, capsys):
    seed_calls(conn)  # older rows have no backend: they ran through Claude Code
    conn.execute(
        "INSERT INTO llm_calls (at, step, ok, cost_usd, backend) VALUES (?, 'prep', 1, 0.5, 'api')",
        (db.now(),),
    )
    conn.commit()
    s = usage.summary(conn)
    by = {r["backend"]: r for r in s["by_backend"]}
    assert by["api"]["calls"] == 1 and by["api"]["cost_usd"] == pytest.approx(0.5)
    assert by["claude_code"]["calls"] == 3 and by["claude_code"]["cost_usd"] == pytest.approx(0.21)
    assert "billed to your Anthropic account" in s["note"]
    cli.main(["stats"])
    out = capsys.readouterr().out
    assert "API key (billed)" in out and "Claude Code (plan)" in out


@pytest.mark.parametrize(
    ("module", "step"),
    [
        ("prep", "prep"),
        ("tagging", "tagging"),
        ("scoring", "scoring"),
        ("analyze", "analyze"),
        ("training", "training"),
        ("tag_merge", "tag_merge"),
    ],
)
def test_call_sites_name_their_step(module, step):
    import importlib
    import inspect

    src = inspect.getsource(importlib.import_module(f"videomentor.{module}"))
    assert f'step="{step}"' in src


def test_analyze_passes_item_id(conn, monkeypatch):
    from videomentor import analyze
    from videomentor.sources import youtube

    a = add(conn, "aaaaaaaaaaa")
    library.decide(conn, a, "prioritize", "c1")
    monkeypatch.setattr(youtube, "fetch_transcript", lambda vid, prof: None)
    seen = {}

    def fake(prompt, **kw):
        seen.update(kw)
        return {"summary": "S", "key_points": [], "moments": [], "learnings": []}

    monkeypatch.setattr(llm, "structured", fake)
    analyze.analyze_item(conn, db.get_item(conn, a), chrome_profile="P", model="sonnet")
    assert seen["step"] == "analyze" and seen["item_id"] == a


# --- Task 2: the signal at decision time -------------------------------------


def test_decision_saves_signal(conn):
    a = add(conn, "aaaaaaaaaaa")
    conn.execute("UPDATE items SET signal = 4 WHERE id = ?", (a,))
    library.decide(conn, a, "keep", "c1")
    conn.execute("UPDATE items SET signal = 2 WHERE id = ?", (a,))  # rescored later
    row = conn.execute("SELECT signal FROM decisions WHERE item_id = ?", (a,)).fetchone()
    assert row["signal"] == 4


def test_decisions_signal_migration(tmp_path):
    import sqlite3

    path = tmp_path / "old.db"
    c = sqlite3.connect(path)
    c.execute(
        "CREATE TABLE decisions (id INTEGER PRIMARY KEY, item_id TEXT, action TEXT,"
        " batch TEXT, at TEXT)"
    )
    c.commit()
    c.close()
    c = db.connect(path)
    db.init(c)
    assert "signal" in {r["name"] for r in c.execute("PRAGMA table_info(decisions)")}
    c.close()
