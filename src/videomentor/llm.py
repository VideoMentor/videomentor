"""Structured LLM calls through the local ``claude -p`` CLI.

Runs on your Claude plan, so there's no API key. Calls are stripped down: no
tools, no MCP servers, no settings or plugins, and no saved session.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile


class LLMError(Exception):
    pass


def claude_binary() -> str:
    path = shutil.which("claude")
    if not path:
        raise LLMError("the `claude` CLI is not on PATH")
    return path


def structured(prompt: str, *, system: str, schema: dict, model: str, timeout: int = 300) -> dict:
    """Send one prompt and return the JSON object matching ``schema``."""
    cmd = [
        claude_binary(),
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
            raise LLMError(f"claude timed out after {timeout}s") from e
    if proc.returncode != 0:
        raise LLMError(f"claude exited {proc.returncode}: {(proc.stderr or proc.stdout)[-500:]}")
    try:
        events = json.loads(proc.stdout)
    except json.JSONDecodeError as e:
        raise LLMError(f"unparseable claude output: {proc.stdout[-500:]}") from e
    result = events[-1] if isinstance(events, list) else events
    if result.get("is_error"):
        raise LLMError(f"claude error: {result.get('result')}")
    out = result.get("structured_output")
    if out is None:
        try:
            out = json.loads(result.get("result") or "")
        except json.JSONDecodeError as e:
            raise LLMError("claude returned no structured output") from e
    return out
