"""Choosing the AI backend, the monthly cost cap, and running cleanly with no AI."""

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from conftest import add
from videomentor import ai, db, llm, llm_api, sync
from videomentor.api import create_app
from videomentor.config import Settings, load_settings
from videomentor.worker import Worker

FAKE_KEY = "sk-ant-api03-FAKEKEYdonotleak1234567890"


@pytest.fixture
def cli_present(monkeypatch):
    monkeypatch.setattr(llm.shutil, "which", lambda name: "/fake/claude")


@pytest.fixture
def cli_missing(monkeypatch):
    monkeypatch.setattr(llm.shutil, "which", lambda name: None)


def add_call(conn, *, cost, backend="api", at=None):
    conn.execute(
        "INSERT INTO llm_calls (at, step, ok, cost_usd, backend) VALUES (?, 'prep', 1, ?, ?)",
        (at or db.now(), cost, backend),
    )
    conn.commit()


def test_auto_prefers_claude_code(cli_present, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", FAKE_KEY)
    assert ai.backend(Settings()) == "claude_code"


def test_auto_uses_api_with_key_only(cli_missing, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", FAKE_KEY)
    assert ai.backend(Settings()) == "api"


def test_off_without_either(cli_missing):
    assert ai.backend(Settings()) == "off"


def test_explicit_choice_that_is_unavailable_is_off(cli_missing, monkeypatch):
    assert ai.backend(Settings(ai_backend="claude_code")) == "off"
    assert ai.backend(Settings(ai_backend="api")) == "off"
    monkeypatch.setenv("ANTHROPIC_API_KEY", FAKE_KEY)
    assert ai.backend(Settings(ai_backend="api")) == "api"
    assert ai.backend(Settings(ai_backend="off")) == "off"


def test_cap_blocks_at_limit(conn, cli_missing, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", FAKE_KEY)
    s = Settings(ai_backend="api")
    add_call(conn, cost=4.99)
    assert ai.allowed(conn, s) == (True, None)
    add_call(conn, cost=0.01)
    assert ai.allowed(conn, s) == (False, "AI paused: this month's $5.00 limit is used")
    st = ai.status(conn, s)
    assert st["paused"] is True and st["month_cost_usd"] == pytest.approx(5.0)
    assert st["reason"] == "AI paused: this month's $5.00 limit is used"


def test_cap_ignores_claude_code_rows(conn, cli_present, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", FAKE_KEY)
    add_call(conn, cost=9.0, backend="claude_code")
    add_call(conn, cost=9.0, backend=None)  # older rows count as claude_code
    assert ai.month_cost(conn) == 0
    assert ai.allowed(conn, Settings(ai_backend="api")) == (True, None)
    # The cap applies only when the effective backend is the API.
    add_call(conn, cost=9.0)
    assert ai.allowed(conn, Settings(ai_backend="claude_code")) == (True, None)


def test_month_resets(conn, cli_missing, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", FAKE_KEY)
    month_start = datetime.now().astimezone().replace(day=1, hour=0, minute=0, second=0)
    last_month = (month_start - timedelta(minutes=1)).astimezone(UTC)
    add_call(conn, cost=50.0, at=last_month.isoformat(timespec="seconds"))
    add_call(conn, cost=1.25)
    assert ai.month_cost(conn) == pytest.approx(1.25)
    assert ai.allowed(conn, Settings(ai_backend="api")) == (True, None)


def test_off_reason_is_plain(conn, cli_missing):
    ok, reason = ai.allowed(conn, Settings(ai_backend="off"))
    assert not ok and reason == "AI is off"
    ok, reason = ai.allowed(conn, Settings())
    assert not ok and "no API key" in reason


def test_worker_makes_no_calls_when_off(conn, monkeypatch):
    add(conn, "aaaaaaaaaaa")
    conn.execute("UPDATE items SET prep_status = 'pending', enrich_status = 'done'")
    conn.commit()
    calls = []
    monkeypatch.setattr(llm, "structured", lambda *a, **k: calls.append(1))
    monkeypatch.setattr(sync, "enrich_pending", lambda conn, settings: 0)  # no AI, no network
    worker = Worker(Settings(ai_backend="off"))
    worker.prep_tick()
    assert calls == []
    item = db.get_item(conn, "yt:aaaaaaaaaaa")
    assert item["prep_attempts"] == 0 and item["prep_status"] == "pending"
    assert worker.state["last_error"] is None


def test_analysis_tick_waits_when_off(conn, monkeypatch):
    from videomentor import library

    a = add(conn, "aaaaaaaaaaa")
    library.decide(conn, a, "prioritize", "c1")
    calls = []
    monkeypatch.setattr(llm, "structured", lambda *a, **k: calls.append(1))
    worker = Worker(Settings(ai_backend="off"))
    assert worker.analysis_tick() is None
    assert calls == []
    assert db.get_item(conn, a)["analysis_status"] == "queued"


def test_structured_raises_when_off_and_records_backend(cli_present, monkeypatch):
    ai.configure(Settings(ai_backend="off"))
    with pytest.raises(llm.LLMError, match="AI is off"):
        llm.structured("hi", system="S", schema={"type": "object"}, model="haiku")
    ai.configure(Settings())
    rows = []
    llm.set_recorder(rows.append)
    monkeypatch.setattr(llm, "_run", lambda *a: {"ok": True})
    assert llm.structured("hi", system="S", schema={"type": "object"}, model="haiku")
    assert rows[0]["backend"] == "claude_code"


def test_real_client_retries_once(monkeypatch):
    seen = {}

    def fake(**kw):
        seen.update(kw)
        raise RuntimeError("stop here")

    monkeypatch.setattr(llm_api.anthropic, "Anthropic", fake)
    monkeypatch.setenv("ANTHROPIC_API_KEY", FAKE_KEY)
    with pytest.raises(RuntimeError):
        llm_api._get_client({})
    assert seen == {"api_key": FAKE_KEY, "max_retries": 1}


@pytest.fixture
def client(conn, cli_missing):
    settings = load_settings()
    app = create_app(settings, run_worker=False)
    with TestClient(app) as c:
        c.get(f"/pair?code={settings.pair_code}", follow_redirects=False)
        yield c


def test_put_ai_validates_and_saves(client):
    assert client.put("/api/ai", json={"backend": "gpt"}).status_code == 422
    assert client.put("/api/ai", json={"cap_usd": 1000.01}).status_code == 422
    assert client.put("/api/ai", json={"cap_usd": -1}).status_code == 422
    r = client.put("/api/ai", json={"backend": "api", "cap_usd": 12.5})
    assert r.status_code == 200
    body = r.json()
    assert body["choice"] == "api" and body["cap_usd"] == 12.5
    assert body["backend"] == "off"  # no key in tests
    saved = load_settings()
    assert saved.ai_backend == "api" and saved.ai_monthly_cap_usd == 12.5
    r = client.put("/api/ai", json={"backend": "off"})
    assert r.json()["choice"] == "off" and r.json()["cap_usd"] == 12.5
    assert client.get("/api/ai").json() == r.json()


def test_status_has_ai(client):
    st = client.get("/api/status").json()["ai"]
    assert set(st) >= {"backend", "cap_usd", "month_cost_usd", "paused", "reason"}
    assert st["backend"] == "off" and st["paused"] is True and st["reason"]


def test_check_reports_off(client, monkeypatch):
    calls = []
    monkeypatch.setattr(llm, "structured", lambda *a, **k: calls.append(k))
    r = client.post("/api/ai/check").json()
    assert r["ok"] is False and r["backend"] == "off" and "AI is off" in r["message"]
    assert calls == []


def test_check_makes_one_tiny_call(client, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", FAKE_KEY)
    calls = []

    def fake(prompt, **kw):
        calls.append(kw)
        return {"ok": True}

    monkeypatch.setattr(llm, "structured", fake)
    r = client.post("/api/ai/check").json()
    assert r["ok"] is True and r["backend"] == "api"
    (kw,) = calls
    assert kw["step"] == "check" and kw["model"] == "haiku"


def test_training_fails_fast_when_off(client, conn, monkeypatch):
    client.put("/api/ai", json={"backend": "off"})
    started = []
    monkeypatch.setattr("videomentor.training.start_thread", lambda fn: started.append(fn))
    r = client.post("/api/training", json={"tag": "MCP"})
    assert r.status_code == 409 and r.json() == {"detail": "AI is off"}
    assert started == []


def test_cli_train_and_tag_draft_fail_fast_when_off(conn, monkeypatch):
    from types import SimpleNamespace

    from videomentor import cli

    calls = []
    monkeypatch.setattr(llm, "structured", lambda *a, **k: calls.append(k))
    off = Settings(ai_backend="off")
    with pytest.raises(SystemExit, match="AI is off"):
        cli.cmd_train(SimpleNamespace(tag="MCP", goal=None, minutes=None), off)
    with pytest.raises(SystemExit, match="AI is off"):
        cli.cmd_tags(SimpleNamespace(draft=True), off)
    assert calls == []
    assert conn.execute("SELECT COUNT(*) FROM training_modules").fetchone()[0] == 0
