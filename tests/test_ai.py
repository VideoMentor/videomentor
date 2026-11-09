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
    llm_api.set_key(FAKE_KEY)
    assert ai.backend(Settings()) == "claude_code"


def test_auto_uses_api_with_key_only(cli_missing, monkeypatch):
    llm_api.set_key(FAKE_KEY)
    assert ai.backend(Settings()) == "api"


def test_off_without_either(cli_missing):
    assert ai.backend(Settings()) == "off"


def test_explicit_choice_that_is_unavailable_is_off(cli_missing, monkeypatch):
    assert ai.backend(Settings(ai_backend="claude_code")) == "off"
    assert ai.backend(Settings(ai_backend="api")) == "off"
    llm_api.set_key(FAKE_KEY)
    assert ai.backend(Settings(ai_backend="api")) == "api"
    assert ai.backend(Settings(ai_backend="off")) == "off"


def test_cap_blocks_at_limit(conn, cli_missing, monkeypatch):
    llm_api.set_key(FAKE_KEY)
    s = Settings(ai_backend="api")
    add_call(conn, cost=4.99)
    assert ai.allowed(conn, s) == (True, None)
    add_call(conn, cost=0.01)
    assert ai.allowed(conn, s) == (False, "AI paused: this month's $5.00 limit is used")
    st = ai.status(conn, s)
    assert st["paused"] is True and st["month_cost_usd"] == pytest.approx(5.0)
    assert st["reason"] == "AI paused: this month's $5.00 limit is used"


def test_cap_ignores_claude_code_rows(conn, cli_present, monkeypatch):
    llm_api.set_key(FAKE_KEY)
    add_call(conn, cost=9.0, backend="claude_code")
    add_call(conn, cost=9.0, backend=None)  # older rows count as claude_code
    assert ai.month_cost(conn) == 0
    assert ai.allowed(conn, Settings(ai_backend="api")) == (True, None)
    # The cap applies only when the effective backend is the API.
    add_call(conn, cost=9.0)
    assert ai.allowed(conn, Settings(ai_backend="claude_code")) == (True, None)


def test_month_resets(conn, cli_missing, monkeypatch):
    llm_api.set_key(FAKE_KEY)
    today = datetime.now()
    month_start = datetime(today.year, today.month, 1).astimezone()
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
    llm_api.set_key(FAKE_KEY)
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
    llm_api.set_key(FAKE_KEY)
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


def unprepped(conn, vid):
    item_id = add(conn, vid)
    conn.execute(
        "UPDATE items SET prep_status = 'pending', why = NULL, category = NULL, topics = '[]',"
        " enrich_status = 'done' WHERE id = ?",
        (item_id,),
    )
    conn.commit()
    return item_id


def test_deck_deals_unprepped_items_when_ai_is_off(client, conn):
    a = unprepped(conn, "aaaaaaaaaaa")
    cards = client.get("/api/deck?deck=main&n=10").json()["cards"]
    assert [c["id"] for c in cards] == [a] and not cards[0]["why"]
    assert client.get("/api/status").json()["counts"]["inbox"] == 1
    pack = client.get("/api/offline-pack").json()
    assert [c["id"] for c in pack["decks"]["main"]] == [a]


def test_deck_waits_for_prep_when_ai_is_allowed(client, conn, monkeypatch):
    unprepped(conn, "aaaaaaaaaaa")
    llm_api.set_key(FAKE_KEY)
    assert client.get("/api/deck?deck=main&n=10").json()["cards"] == []
    assert client.get("/api/status").json()["counts"]["inbox"] == 0


def test_put_ai_keeps_a_new_pairing_code(client):
    on_disk = load_settings()
    on_disk.pair_code = "1111-2222-3333"
    from videomentor.config import save_settings

    save_settings(on_disk)
    assert client.put("/api/ai", json={"cap_usd": 7}).status_code == 200
    assert load_settings().pair_code == "1111-2222-3333"


def test_raising_the_cap_resumes_work(client, conn, monkeypatch):
    llm_api.set_key(FAKE_KEY)
    client.put("/api/ai", json={"backend": "api", "cap_usd": 5})
    add_call(conn, cost=5.0)
    assert client.get("/api/ai").json()["paused"] is True
    r = client.put("/api/ai", json={"cap_usd": 10}).json()
    assert r["paused"] is False and r["reason"] is None
    assert ai.allowed(conn, load_settings()) == (True, None)


def test_cli_prep_and_analyze_respect_ai(conn, monkeypatch):
    from types import SimpleNamespace

    from videomentor import cli

    a = unprepped(conn, "aaaaaaaaaaa")
    calls = []
    monkeypatch.setattr(llm, "structured", lambda *a, **k: calls.append(k))
    off = Settings(ai_backend="off")
    with pytest.raises(SystemExit, match="AI is off"):
        cli.cmd_prep(SimpleNamespace(retry_failed=False, limit=None), off)
    with pytest.raises(SystemExit, match="AI is off"):
        cli.cmd_analyze(SimpleNamespace(upgrade=False, retry_failed=False, id=a, count=1), off)
    llm_api.set_key(FAKE_KEY)
    monkeypatch.setattr(llm.shutil, "which", lambda name: None)
    add_call(conn, cost=5.0)
    with pytest.raises(SystemExit, match=r"\$5.00 limit is used"):
        cli.cmd_prep(SimpleNamespace(retry_failed=False, limit=None), Settings(ai_backend="api"))
    assert calls == []
    item = db.get_item(conn, a)
    assert item["prep_status"] == "pending" and item["prep_attempts"] == 0


def test_month_start_across_dst(monkeypatch):
    import time

    real = ai.datetime

    class Frozen(real):
        @classmethod
        def now(cls, tz=None):
            return real(2026, 11, 9, 12, 0, tzinfo=tz) if tz else real(2026, 11, 9, 12, 0)

    monkeypatch.setenv("TZ", "America/Chicago")
    time.tzset()
    monkeypatch.setattr(ai, "datetime", Frozen)
    try:
        # Nov 1 2026 midnight is still CDT (UTC-5); DST ends at 2am that day.
        assert ai._month_start_utc() == "2026-11-01T05:00:00+00:00"
    finally:
        monkeypatch.undo()
        time.tzset()


def test_switching_off_mid_batch_counts_no_failure(conn, monkeypatch):
    from videomentor import analyze, library, prep
    from videomentor.sources import youtube

    a = unprepped(conn, "aaaaaaaaaaa")

    def off(*a, **k):
        raise llm.AIUnavailable("AI is off")

    monkeypatch.setattr(llm, "structured", off)
    with pytest.raises(llm.AIUnavailable):
        prep.prep_batch(conn, prep.pending(conn, 20), "haiku")
    item = db.get_item(conn, a)
    assert item["prep_status"] == "pending" and item["prep_attempts"] == 0

    b = add(conn, "bbbbbbbbbbb")
    library.decide(conn, b, "prioritize", "c1")
    monkeypatch.setattr(youtube, "fetch_transcript", lambda vid, prof: None)
    with pytest.raises(llm.AIUnavailable):
        analyze.analyze_item(conn, db.get_item(conn, b), chrome_profile="P", model="sonnet")
    assert db.get_item(conn, b)["analysis_status"] == "queued"


# --- 0.16.0 review fixes -------------------------------------------------------


def test_claude_code_never_sees_the_api_key(monkeypatch):
    """`claude -p` would bill an ANTHROPIC_API_KEY in its environment instead of the plan."""
    import os
    import subprocess

    monkeypatch.setenv("ANTHROPIC_API_KEY", FAKE_KEY)
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "tok-FAKE")
    seen = {}

    def run(cmd, **kw):
        seen.update(kw)
        return subprocess.CompletedProcess(
            cmd, 0, stdout='{"structured_output": {"ok": true}}', stderr=""
        )

    monkeypatch.setattr(llm.subprocess, "run", run)
    assert llm._run("/fake/claude", "p", "s", {"type": "object"}, "haiku", 5, {}) == {"ok": True}
    env = seen["env"]
    assert "ANTHROPIC_API_KEY" not in env and "ANTHROPIC_AUTH_TOKEN" not in env
    assert env["PATH"] == os.environ["PATH"] and env["HOME"] == os.environ["HOME"]


def test_cli_startup_moves_the_key_out_of_the_environment(conn, cli_missing, monkeypatch):
    import os

    from videomentor import cli

    monkeypatch.setenv("ANTHROPIC_API_KEY", FAKE_KEY)
    cli.main(["status"])
    assert "ANTHROPIC_API_KEY" not in os.environ  # no child process can inherit it
    assert llm_api.key() == FAKE_KEY
    assert ai.backend(Settings()) == "api"
    assert ai.backend(Settings(ai_backend="api")) == "api"


def test_serve_startup_moves_the_key_out_of_the_environment(conn, cli_missing, monkeypatch):
    import os

    monkeypatch.setenv("ANTHROPIC_API_KEY", FAKE_KEY)
    create_app(Settings(pair_code="T"), run_worker=False)
    assert "ANTHROPIC_API_KEY" not in os.environ
    assert llm_api.key() == FAKE_KEY
    assert ai.backend(Settings()) == "api"


def test_backend_ignores_a_key_left_in_the_environment(cli_missing, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", FAKE_KEY)
    assert ai.backend(Settings(ai_backend="api")) == "off"
    llm_api.set_key(FAKE_KEY)
    assert ai.backend(Settings(ai_backend="api")) == "api"


class CountingClient:
    def __init__(self):
        self.calls = 0
        self.messages = self
        self.beta = self

    def create(self, **kw):
        self.calls += 1
        raise AssertionError("no SDK call once the cap is reached")


def test_structured_checks_the_cap_on_every_call(conn, cli_missing):
    llm_api.set_key(FAKE_KEY)
    client = CountingClient()
    llm_api.set_client(client)
    ai.configure(Settings(ai_backend="api", ai_monthly_cap_usd=5))
    add_call(conn, cost=5.0)
    with pytest.raises(llm.AIUnavailable, match=r"\$5.00 limit is used"):
        llm.structured("hi", system="S", schema={"type": "object"}, model="haiku")
    assert client.calls == 0


def test_cap_does_not_stop_claude_code(conn, cli_present, monkeypatch):
    llm_api.set_key(FAKE_KEY)
    ai.configure(Settings(ai_backend="auto", ai_monthly_cap_usd=5))
    add_call(conn, cost=50.0)
    monkeypatch.setattr(llm, "_run", lambda *a: {"ok": True})
    assert llm.structured("hi", system="S", schema={"type": "object"}, model="haiku")


def test_cli_prep_stops_when_the_cap_is_reached_partway(conn, cli_missing, monkeypatch):
    import re
    from types import SimpleNamespace

    from videomentor import cli, usage

    ids = [unprepped(conn, f"{c * 11}") for c in "abcde"]
    llm_api.set_key(FAKE_KEY)
    settings = Settings(ai_backend="api", ai_monthly_cap_usd=5, prep_batch_size=1)
    ai.configure(settings)
    usage.install()
    sent = []

    def fake_call(prompt, *, row, **kw):
        sent.append(prompt)
        row["cost_usd"] = 3.0
        (item_id,) = re.findall(r"id: (yt:\w+)", prompt)
        return {"items": [{"id": item_id, "why": "w", "topics": [], "category": "learning"}]}

    monkeypatch.setattr(llm_api, "call", fake_call)
    with pytest.raises(SystemExit, match=r"\$5.00 limit is used"):
        cli.cmd_prep(SimpleNamespace(retry_failed=False, limit=None), settings)
    assert len(sent) == 2  # $3 + $3 reaches the $5 cap; the third call never goes out
    items = [db.get_item(conn, i) for i in ids]
    assert sum(i["prep_status"] == "done" for i in items) == 2
    left = [i for i in items if i["prep_status"] != "done"]
    assert all(i["prep_status"] == "pending" and i["prep_attempts"] == 0 for i in left)


def test_cli_analyze_requeues_the_rest_when_the_cap_is_reached(conn, monkeypatch):
    from types import SimpleNamespace

    from videomentor import analyze, cli, library

    ids = [add(conn, f"{c * 11}") for c in "ab"]
    for n, i in enumerate(ids):
        library.decide(conn, i, "prioritize", f"p{n}")
    conn.commit()

    def paused(conn, item, **kw):
        conn.execute("UPDATE items SET analysis_status = 'queued' WHERE id = ?", (item["id"],))
        raise llm.AIUnavailable("AI paused: this month's $5.00 limit is used")

    monkeypatch.setattr(analyze, "analyze_item", paused)
    monkeypatch.setattr(cli.ai, "allowed", lambda conn, s: (True, None))
    with pytest.raises(SystemExit, match="limit is used"):
        cli.cmd_analyze(
            SimpleNamespace(upgrade=False, retry_failed=False, id=None, count=2), Settings()
        )
    assert {db.get_item(conn, i)["analysis_status"] for i in ids} == {"queued"}
