"""Structured LLM calls through the Anthropic API (the official ``anthropic`` SDK).

The key comes only from ``ANTHROPIC_API_KEY`` in the environment. Error text is
fixed wording plus a status code, never the SDK's own message, so the key can't
reach an error, the usage row or the logs.
"""

from __future__ import annotations

import copy
import json
import logging
import os
import time
from typing import Any

import anthropic

from videomentor.llm import _fail

log = logging.getLogger(__name__)

MAX_TOKENS = 16000
FALLBACK_BETA = "server-side-fallback-2026-07-01"

MODELS = {
    "haiku": "claude-haiku-5-5",
    "sonnet": "claude-sonnet-5-5",
    "opus": "claude-opus-5-5",
}

# List prices in USD per million tokens: (input, output).
PRICES = {
    "claude-haiku-5-5": (0.10, 0.50),
    "claude-sonnet-5-5": (2.0, 10.0),
    "claude-opus-5-5": (4.0, 20.0),
}
CACHE_READ = 0.1
CACHE_WRITE = 1.25

_client: Any = None


def set_client(client: Any) -> None:
    """Use this client instead of a real one (tests); None goes back to the default."""
    global _client
    _client = client


def _get_client(row: dict) -> Any:
    """The injected client, or a real one built from ``ANTHROPIC_API_KEY`` only.

    The key is passed explicitly so the SDK never falls back to an auth token or a
    profile on disk.
    """
    global _client
    if _client is None:
        key = os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise _fail(row, "auth", "No Anthropic API key is set")
        _client = anthropic.Anthropic(api_key=key, max_retries=1)
    return _client


def model_id(short: str) -> str:
    return MODELS.get(short, short)


# Models that get the server-side refusal fallback (exact IDs; haiku has none).
FALLBACK_MODELS = frozenset({"claude-sonnet-5-5", "claude-opus-5-5"})


def _uses_fallbacks(mid: str) -> bool:
    return mid in FALLBACK_MODELS


def cost_usd(model_id: str, usage: Any) -> float | None:
    """List-price cost of one call, or None for an unknown model or missing usage."""
    price = PRICES.get(model_id)
    if price is None or usage is None:
        return None
    inp, out = price

    def n(name: str) -> int:
        return getattr(usage, name, None) or 0

    total = (
        n("input_tokens") * inp
        + n("output_tokens") * out
        + n("cache_read_input_tokens") * inp * CACHE_READ
        + n("cache_creation_input_tokens") * inp * CACHE_WRITE
    )
    return total / 1e6


def strict_schema(schema: dict) -> dict:
    """A copy of ``schema`` where every object has ``required`` and no extra properties."""
    out = copy.deepcopy(schema)
    _strict(out)
    return out


def _strict(node: Any) -> None:
    if isinstance(node, list):
        for n in node:
            _strict(n)
        return
    if not isinstance(node, dict):
        return
    props = node.get("properties")
    if node.get("type") == "object" or isinstance(props, dict):
        node.setdefault("additionalProperties", False)
        if isinstance(props, dict):
            node.setdefault("required", list(props))
    if isinstance(props, dict):
        for p in props.values():
            _strict(p)
    for key in ("items", "anyOf", "allOf", "oneOf", "prefixItems"):
        if key in node:
            _strict(node[key])
    for key in ("$defs", "definitions"):
        if isinstance(node.get(key), dict):
            for d in node[key].values():
                _strict(d)


def _usage(row: dict, response: Any, mid: str) -> None:
    usage = getattr(response, "usage", None)
    row["model"] = getattr(response, "model", None) or mid
    row["input_tokens"] = getattr(usage, "input_tokens", None)
    row["output_tokens"] = getattr(usage, "output_tokens", None)
    row["cache_read_tokens"] = getattr(usage, "cache_read_input_tokens", None)
    row["cache_creation_tokens"] = getattr(usage, "cache_creation_input_tokens", None)
    # A model outside the price table (a server-side fallback, say) is costed at the
    # requested model's price, so the monthly cap never counts a call as free.
    cost = cost_usd(row["model"], usage)
    row["cost_usd"] = cost if cost is not None else cost_usd(mid, usage)


def _request(
    prompt: str, system: str, schema: dict, mid: str, effort: str, timeout: int, row: dict
) -> Any:
    client = _get_client(row)
    kw: dict = {
        "model": mid,
        "max_tokens": MAX_TOKENS,
        "system": system,
        "messages": [{"role": "user", "content": prompt}],
        "output_config": {
            "format": {"type": "json_schema", "schema": strict_schema(schema)},
            "effort": effort,
        },
        "timeout": timeout,
    }
    if _uses_fallbacks(mid):
        return client.beta.messages.create(**kw, betas=[FALLBACK_BETA], fallbacks="default")
    return client.messages.create(**kw)


def _api_error(row: dict, e: anthropic.AnthropicError, timeout: int):
    """Map an SDK error to an LLMError with fixed text. Never uses the SDK's message."""
    status = getattr(e, "status_code", None)
    if isinstance(e, anthropic.AuthenticationError | anthropic.PermissionDeniedError):
        err = _fail(row, "auth", f"Anthropic API refused the key (status {status})")
    elif isinstance(e, anthropic.RateLimitError):
        err = _fail(row, "rate_limit", f"Anthropic API rate limit reached (status {status})")
    elif isinstance(e, anthropic.APITimeoutError):
        err = _fail(row, "timeout", f"Anthropic API timed out after {timeout}s")
    elif isinstance(e, anthropic.APIConnectionError):
        err = _fail(row, "timeout", "could not connect to the Anthropic API")
    elif isinstance(e, anthropic.APIStatusError):
        err = _fail(row, "exit", f"Anthropic API error (status {status})")
    else:
        err = _fail(row, "exit", "Anthropic API call failed")
    # Logged by class name only: the SDK's message could echo request details.
    log.warning("Anthropic API call failed: %s", type(e).__name__)
    return err


def call(
    prompt: str,
    *,
    system: str,
    schema: dict,
    model: str,
    effort: str,
    timeout: int,
    row: dict,
) -> dict:
    """Send one prompt and return the JSON object matching ``schema``; fills ``row``."""
    mid = model_id(model)
    row["model"] = mid
    started = time.monotonic()
    try:
        response = _request(prompt, system, schema, mid, effort, timeout, row)
    except anthropic.AnthropicError as e:
        err = _api_error(row, e, timeout)
        row["duration_ms"] = int((time.monotonic() - started) * 1000)
        raise err from None
    row["duration_ms"] = int((time.monotonic() - started) * 1000)
    _usage(row, response, mid)

    stop = getattr(response, "stop_reason", None)
    if stop == "refusal":
        raise _fail(row, "refusal", "the model declined to answer")
    if stop == "max_tokens":
        raise _fail(row, "max_tokens", f"the answer was cut off at {MAX_TOKENS} tokens")
    text = next(
        (b.text for b in getattr(response, "content", None) or [] if b.type == "text"), None
    )
    if not text:
        raise _fail(row, "unparseable", "the Anthropic API returned no text")
    try:
        out = json.loads(text)
    except json.JSONDecodeError:
        raise _fail(row, "unparseable", "the Anthropic API returned invalid JSON") from None
    if not isinstance(out, dict):
        raise _fail(row, "unparseable", "the Anthropic API returned JSON that is not an object")
    return out
