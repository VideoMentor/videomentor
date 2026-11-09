"""The Anthropic API backend for llm.structured (no network: a stub client is injected)."""

import json
import logging
from types import SimpleNamespace

import anthropic
import httpx2
import pytest

from videomentor import llm, llm_api

FAKE_KEY = "sk-ant-api03-FAKEKEYdonotleak1234567890"
SCHEMA = {"type": "object", "properties": {"items": {"type": "array"}}, "required": ["items"]}


def response(
    text='{"items": []}',
    *,
    stop_reason="end_turn",
    model="claude-haiku-5-5",
    usage=None,
    blocks=None,
):
    if usage is None:
        usage = SimpleNamespace(
            input_tokens=120,
            output_tokens=40,
            cache_read_input_tokens=None,
            cache_creation_input_tokens=None,
        )
    if blocks is None:
        blocks = [
            SimpleNamespace(type="thinking", thinking="hmm"),
            SimpleNamespace(type="text", text=text),
        ]
    return SimpleNamespace(content=blocks, stop_reason=stop_reason, model=model, usage=usage)


class Endpoint:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def create(self, **kw):
        self.calls.append(kw)
        if isinstance(self.result, BaseException):
            raise self.result
        return self.result


class StubClient:
    def __init__(self, result):
        self.messages = Endpoint(result)
        self.beta = SimpleNamespace(messages=Endpoint(result))


@pytest.fixture
def stub():
    def install(result):
        client = StubClient(result)
        llm_api.set_client(client)
        return client

    yield install
    llm_api.set_client(None)


def call(model="haiku", row=None):
    return llm_api.call(
        "hello",
        system="SYS",
        schema=SCHEMA,
        model=model,
        effort="low",
        timeout=30,
        row={} if row is None else row,
    )


def test_returns_parsed_json_and_fills_usage(stub):
    client = stub(response())
    row: dict = {}
    assert call(row=row) == {"items": []}
    assert row["input_tokens"] == 120
    assert row["output_tokens"] == 40
    assert row["model"] == "claude-haiku-5-5"
    assert row["cost_usd"] == pytest.approx(120 * 0.10 / 1e6 + 40 * 0.50 / 1e6)
    assert isinstance(row["duration_ms"], int)
    (kw,) = client.messages.calls
    assert kw["model"] == "claude-haiku-5-5"
    assert kw["max_tokens"] == 16000
    assert kw["system"] == "SYS"
    assert kw["messages"] == [{"role": "user", "content": "hello"}]
    assert kw["output_config"]["effort"] == "low"
    assert kw["output_config"]["format"]["type"] == "json_schema"
    assert kw["output_config"]["format"]["schema"]["additionalProperties"] is False
    for banned in ("temperature", "top_p", "top_k", "thinking"):
        assert banned not in kw
    assert client.beta.messages.calls == []


def test_maps_short_model_names():
    assert llm_api.model_id("haiku") == "claude-haiku-5-5"
    assert llm_api.model_id("sonnet") == "claude-sonnet-5-5"
    assert llm_api.model_id("opus") == "claude-opus-5-5"
    assert llm_api.model_id("custom-x") == "custom-x"


def test_cost_includes_cache_and_unknown_model_is_none():
    usage = SimpleNamespace(
        input_tokens=1000,
        output_tokens=100,
        cache_read_input_tokens=2000,
        cache_creation_input_tokens=400,
    )
    assert llm_api.cost_usd("claude-sonnet-5-5", usage) == pytest.approx(
        (1000 * 2 + 100 * 10 + 2000 * 2 * 0.1 + 400 * 2 * 1.25) / 1e6
    )
    assert llm_api.cost_usd("custom-x", usage) is None
    assert llm_api.cost_usd("claude-haiku-5-5", None) is None


def test_refusal_raises_with_kind(stub):
    stub(response(text="", stop_reason="refusal"))
    row: dict = {}
    with pytest.raises(llm.LLMError):
        call(row=row)
    assert row["error_kind"] == "refusal"
    assert row["input_tokens"] == 120  # usage is still recorded


def test_max_tokens_raises_with_kind(stub):
    stub(response(text='{"items": [', stop_reason="max_tokens"))
    row: dict = {}
    with pytest.raises(llm.LLMError):
        call(row=row)
    assert row["error_kind"] == "max_tokens"


def test_invalid_json_raises_unparseable(stub):
    stub(response(text="not json"))
    row: dict = {}
    with pytest.raises(llm.LLMError):
        call(row=row)
    assert row["error_kind"] == "unparseable"


def test_empty_content_raises_unparseable(stub):
    stub(response(blocks=[]))
    row: dict = {}
    with pytest.raises(llm.LLMError):
        call(row=row)
    assert row["error_kind"] == "unparseable"


def test_strict_schema_adds_required_and_no_extra_props():
    schema = {
        "type": "object",
        "properties": {
            "a": {"type": "string"},
            "nested": {"type": "object", "properties": {"x": {"type": "integer"}}},
            "list": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {"p": {"type": "string"}, "q": {"type": "string"}},
                    "required": ["p"],
                },
            },
        },
    }
    before = json.dumps(schema, sort_keys=True)
    out = llm_api.strict_schema(schema)
    assert json.dumps(schema, sort_keys=True) == before  # the CLI path's schema is untouched
    assert out["additionalProperties"] is False
    assert out["required"] == ["a", "nested", "list"]
    nested = out["properties"]["nested"]
    assert nested["additionalProperties"] is False and nested["required"] == ["x"]
    item = out["properties"]["list"]["items"]
    assert item["additionalProperties"] is False
    assert item["required"] == ["p"]  # an existing required list is kept
    assert "additionalProperties" not in out["properties"]["a"]


@pytest.mark.parametrize("short", ["sonnet", "opus"])
def test_sonnet_requests_use_fallbacks(stub, short):
    client = stub(response(model=f"claude-{short}-5-5"))
    assert call(model=short) == {"items": []}
    assert client.messages.calls == []
    (kw,) = client.beta.messages.calls
    assert kw["model"] == f"claude-{short}-5-5"
    assert kw["betas"] == ["server-side-fallback-2026-07-01"]
    assert kw["fallbacks"] == "default"
    assert "output_config" in kw


def _http_response(status):
    req = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    return httpx2.Response(status, request=req)


@pytest.mark.parametrize(
    ("exc", "kind"),
    [
        (
            anthropic.AuthenticationError(
                f"invalid x-api-key {FAKE_KEY}", response=_http_response(401), body=None
            ),
            "auth",
        ),
        (
            anthropic.PermissionDeniedError(
                f"denied for {FAKE_KEY}", response=_http_response(403), body=None
            ),
            "auth",
        ),
        (
            anthropic.RateLimitError(
                f"slow down {FAKE_KEY}", response=_http_response(429), body=None
            ),
            "rate_limit",
        ),
        (
            anthropic.APITimeoutError(
                request=httpx2.Request("POST", f"https://api.anthropic.com/?k={FAKE_KEY}")
            ),
            "timeout",
        ),
        (
            anthropic.APIConnectionError(
                message=f"conn {FAKE_KEY}", request=httpx2.Request("POST", "https://x")
            ),
            "timeout",
        ),
        (
            anthropic.InternalServerError(
                f"boom {FAKE_KEY}", response=_http_response(500), body=None
            ),
            "exit",
        ),
    ],
)
def test_sdk_errors_map_to_kinds(stub, exc, kind):
    stub(exc)
    row: dict = {}
    with pytest.raises(llm.LLMError) as info:
        call(row=row)
    assert row["error_kind"] == kind
    assert FAKE_KEY not in str(info.value)
    assert info.value.__cause__ is None and info.value.__suppress_context__


def test_key_never_in_error_or_row(stub, monkeypatch, caplog):
    monkeypatch.setenv("ANTHROPIC_API_KEY", FAKE_KEY)
    monkeypatch.setattr(llm, "claude_binary", lambda: (_ for _ in ()).throw(llm.LLMError("no")))
    stub(
        anthropic.AuthenticationError(
            f"invalid x-api-key: {FAKE_KEY}", response=_http_response(401), body=None
        )
    )
    rows = []
    llm.set_recorder(rows.append)
    caplog.set_level(logging.DEBUG)
    with pytest.raises(llm.LLMError) as info:
        llm.structured("hello", system="SYS", schema=SCHEMA, model="haiku", step="prep")
    assert FAKE_KEY not in str(info.value)
    assert "401" in str(info.value)
    (r,) = rows
    assert r["error_kind"] == "auth" and r["ok"] == 0
    assert FAKE_KEY not in json.dumps(r, default=str)
    assert FAKE_KEY not in caplog.text
    for rec in caplog.records:
        assert rec.exc_info is None or FAKE_KEY not in str(rec.exc_info[1])


def test_structured_routes_to_api_when_cli_missing_and_key_set(stub, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", FAKE_KEY)
    monkeypatch.setattr(llm.shutil, "which", lambda name: None)
    client = stub(response())
    rows = []
    llm.set_recorder(rows.append)
    out = llm.structured(
        "hello", system="SYS", schema=SCHEMA, model="haiku", step="analyze", effort="medium"
    )
    assert out == {"items": []}
    assert client.messages.calls[0]["output_config"]["effort"] == "medium"
    (r,) = rows
    assert r["ok"] == 1 and r["step"] == "analyze" and r["model"] == "claude-haiku-5-5"
    assert r["cost_usd"] == pytest.approx(120 * 0.10 / 1e6 + 40 * 0.50 / 1e6)


def test_structured_without_cli_or_key_keeps_cli_error(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(llm.shutil, "which", lambda name: None)
    with pytest.raises(llm.LLMError, match="the `claude` CLI is not on PATH"):
        llm.structured("hello", system="SYS", schema=SCHEMA, model="haiku")


def test_no_stub_never_builds_a_real_client(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", FAKE_KEY)
    with pytest.raises(RuntimeError, match="Anthropic API disabled in tests"):
        call()


def test_real_client_uses_only_the_env_key(monkeypatch):
    seen = {}

    def fake_anthropic(**kw):
        seen.update(kw)
        return StubClient(response())

    monkeypatch.setattr(llm_api.anthropic, "Anthropic", fake_anthropic)
    monkeypatch.setenv("ANTHROPIC_API_KEY", FAKE_KEY)
    assert call() == {"items": []}
    assert seen == {"api_key": FAKE_KEY}


def test_missing_key_raises_auth_without_a_client(monkeypatch):
    built = []
    monkeypatch.setattr(llm_api.anthropic, "Anthropic", lambda **kw: built.append(kw))
    row: dict = {}
    with pytest.raises(llm.LLMError, match="No Anthropic API key is set"):
        call(row=row)
    assert row["error_kind"] == "auth"
    assert built == []


def test_fallback_model_is_costed_at_requested_price(stub):
    stub(response(model="claude-some-fallback-9"))
    row: dict = {}
    call(model="sonnet", row=row)
    assert row["model"] == "claude-some-fallback-9"
    assert row["cost_usd"] == pytest.approx(120 * 2 / 1e6 + 40 * 10 / 1e6)


def test_older_sonnet_gets_no_fallback(stub):
    client = stub(response(model="claude-sonnet-4-5"))
    call(model="claude-sonnet-4-5")
    assert client.beta.messages.calls == []
    (kw,) = client.messages.calls
    assert "fallbacks" not in kw and "betas" not in kw
