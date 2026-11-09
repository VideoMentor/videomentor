"""Structured LLM calls through the local ``claude -p`` CLI.

Runs on your Claude plan, so there's no API key. Calls are stripped down: no
tools, no MCP servers, no settings or plugins, and no saved session.
"""

from __future__ import annotations

import hashlib
import json
import logging
import shutil
import subprocess
import tempfile
from collections.abc import Callable

log = logging.getLogger(__name__)


class LLMError(Exception):
    pass


def claude_binary() -> str:
    path = shutil.which("claude")
    if not path:
        raise LLMError("the `claude` CLI is not on PATH")
    return path


# Called with one dict per call (numbers and a prompt hash only); set by usage.install().
Recorder = Callable[[dict], None]
_recorder: Recorder | None = None


def set_recorder(fn: Recorder | None) -> None:
    global _recorder
    _recorder = fn


def _emit(row: dict) -> None:
    if _recorder is None:
        return
    try:
        _recorder(row)
    except Exception:  # tracking must never break the call
        log.warning("recording an LLM call failed", exc_info=True)


def _usage(row: dict, result: object) -> None:
    """Copy the usage numbers from claude's result JSON; anything missing stays null."""
    if not isinstance(result, dict):
        return
    u = result.get("usage") if isinstance(result.get("usage"), dict) else {}
    row["input_tokens"] = u.get("input_tokens")
    row["output_tokens"] = u.get("output_tokens")
    row["cache_read_tokens"] = u.get("cache_read_input_tokens")
    row["cache_creation_tokens"] = u.get("cache_creation_input_tokens")
    row["cost_usd"] = result.get("total_cost_usd")
    row["duration_ms"] = result.get("duration_ms")
    row["duration_api_ms"] = result.get("duration_api_ms")
    models = result.get("modelUsage")
    if isinstance(models, dict) and models:
        row["model"] = ",".join(sorted(models))


def prompt_hash(system: str, schema: dict) -> str:
    return hashlib.sha256(
        (system + "\n" + json.dumps(schema, sort_keys=True)).encode()
    ).hexdigest()[:16]


def structured(
    prompt: str,
    *,
    system: str,
    schema: dict,
    model: str,
    timeout: int = 300,
    step: str = "other",
    item_id: str | None = None,
) -> dict:
    """Send one prompt and return the JSON object matching ``schema``.

    Each call (ok or failed) goes to the recorder, if one is set, as one row of numbers.
    """
    binary = claude_binary()
    row: dict = {
        "step": step,
        "item_id": item_id,
        "model": model,
        "ok": 0,
        "error_kind": None,
        "input_tokens": None,
        "output_tokens": None,
        "cache_read_tokens": None,
        "cache_creation_tokens": None,
        "cost_usd": None,
        "duration_ms": None,
        "duration_api_ms": None,
        "prompt_hash": prompt_hash(system, schema),
        "prompt_chars": len(system) + len(prompt),
    }
    try:
        out = _run(binary, prompt, system, schema, model, timeout, row)
        row["ok"] = 1
        return out
    except LLMError:
        raise
    except Exception:
        row["error_kind"] = "exit"
        raise
    finally:
        _emit(row)


def _fail(row: dict, kind: str, message: str) -> LLMError:
    row["error_kind"] = kind
    return LLMError(message)


def _run(
    binary: str, prompt: str, system: str, schema: dict, model: str, timeout: int, row: dict
) -> dict:
    cmd = [
        binary,
        "-p",
        "--model",
        model,
        "--output-format",
        "json",
        "--no-session-persistence",
        "--tools",
        "",
        "--strict-mcp-config",
        "--setting-sources",
        "",
        "--disable-slash-commands",
        "--system-prompt",
        system,
        "--json-schema",
        json.dumps(schema),
    ]
    # Run from an empty directory so no project CLAUDE.md gets pulled in.
    with tempfile.TemporaryDirectory() as cwd:
        try:
            proc = subprocess.run(
                cmd, input=prompt, capture_output=True, text=True, timeout=timeout, cwd=cwd
            )
        except subprocess.TimeoutExpired as e:
            raise _fail(row, "timeout", f"claude timed out after {timeout}s") from e
    if proc.returncode != 0:
        raise _fail(
            row, "exit", f"claude exited {proc.returncode}: {(proc.stderr or proc.stdout)[-500:]}"
        )
    try:
        events = json.loads(proc.stdout)
    except json.JSONDecodeError as e:
        raise _fail(row, "unparseable", f"unparseable claude output: {proc.stdout[-500:]}") from e
    result = events[-1] if isinstance(events, list) and events else events
    if not isinstance(result, dict):
        raise _fail(row, "unparseable", f"unparseable claude output: {proc.stdout[-500:]}")
    _usage(row, result)
    if result.get("is_error"):
        raise _fail(row, "is_error", f"claude error: {result.get('result')}")
    out = result.get("structured_output")
    if out is None:
        try:
            out = json.loads(result.get("result") or "")
        except json.JSONDecodeError as e:
            raise _fail(row, "no_output", "claude returned no structured output") from e
    return out
