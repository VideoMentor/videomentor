"""Per-item Markdown files under ``~/VideoMentor/items/youtube/``."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from . import db, tagging, transcripts
from .config import library_home


def item_path(video_id: str) -> Path:
    return library_home() / "items" / "youtube" / f"{video_id}.md"


def transcript_path(video_id: str) -> Path:
    return library_home() / "items" / "youtube" / f"{video_id}.transcript.md"


def _stamp(seconds: int) -> str:
    h, rem = divmod(int(seconds), 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def render(
    item: dict, sources: list[str], tags: list[str] | None = None, has_transcript: bool = False
) -> str:
    from .library import posted

    front = {
        "id": item["id"],
        "url": item["url"],
        "title": item.get("title"),
        "channel": item.get("channel"),
        "duration_s": item.get("duration_s"),
        "status": item["status"],
        "priority": bool(item["priority"]),
        "category": item.get("category"),
        "topics": item.get("topics") or [],
        "tags": tags or [],
        "skills": (
            (item.get("analysis") or {}) if isinstance(item.get("analysis"), dict) else {}
        ).get("skills")
        or [],
        "signal": item.get("signal"),
        "posted_at": posted(item)[0],
        "sources": sources,
        "added_at": item["added_at"],
        "analyzed_at": item.get("analyzed_at"),
    }
    lines = ["---"]
    lines += [f"{k}: {json.dumps(v, ensure_ascii=False)}" for k, v in front.items()]
    lines += ["---", "", f"# {item.get('title') or item['video_id']}", ""]
    lines.append(f"[Watch on YouTube]({item['url']}) · {item.get('channel') or ''}")
    if has_transcript:
        name = transcript_path(item["video_id"]).name
        lines += ["", f"Transcript: [{name}]({name})"]
    if item.get("why"):
        lines += ["", f"> Why you saved it: {item['why']}"]
    analysis = item.get("analysis") if isinstance(item.get("analysis"), dict) else None
    if analysis:
        if analysis.get("core_idea"):
            lines += ["", "## Core idea", "", analysis["core_idea"]]
        if analysis.get("useful_for"):
            lines += ["", f"Useful for: {analysis['useful_for']}"]
        lines += ["", "## Summary", "", analysis.get("summary", "")]
        if analysis.get("transcript_source") == "none":
            lines += ["", "_No captions were available; notes come from the description only._"]
        for heading, key in (("Key points", "key_points"), ("Takeaways", "takeaways")):
            if analysis.get(key):
                lines += ["", f"## {heading}", ""] + [f"- {p}" for p in analysis[key]]
        if analysis.get("frameworks"):
            lines += ["", "## Frameworks", ""] + [
                f"- **{f.get('name', '')}**: {f.get('how', '')}" for f in analysis["frameworks"]
            ]
        if analysis.get("try_this_week"):
            lines += ["", "## Try this week", ""] + [
                f"- [ ] {a}" for a in analysis["try_this_week"]
            ]
        if analysis.get("learnings") and not analysis.get("takeaways"):
            lines += ["", "## Learnings", ""] + [f"- {p}" for p in analysis["learnings"]]
        if analysis.get("moments"):
            lines += ["", "## Moments", ""]
            for m in analysis["moments"]:
                tag = f" `{m['tag']}`" if m.get("tag") else ""
                lines.append(
                    f"- [{_stamp(m['t'])}]({item['url']}&t={int(m['t'])}s) {m['label']}{tag}"
                )
        if analysis.get("curriculum_topic"):
            lines += ["", f"Curriculum topic: **{analysis['curriculum_topic']}**"]
    elif item.get("analysis_error"):
        lines += ["", f"_Analysis failed: {item['analysis_error'][:300]}_"]
    if item.get("description"):
        lines += ["", "## Description", "", item["description"].strip()]
    return "\n".join(lines) + "\n"


def render_transcript(item: dict, lines: list[list], window: int = 30) -> str:
    """Captions in ~30-second paragraphs, each starting with its timestamp."""
    out = [
        f"# Transcript: {item.get('title') or item['video_id']}",
        "",
        f"{item['url']} · {item.get('channel') or ''}",
        "",
    ]
    start, words = None, []
    for t, text in lines:
        if start is None or t >= start + window:
            if words:
                out.append(f"[{_stamp(start)}] {' '.join(words)}")
            start, words = t, []
        words.append(text.strip())
    if words:
        out.append(f"[{_stamp(start)}] {' '.join(words)}")
    return "\n".join(out) + "\n"


def write_item(conn: sqlite3.Connection, item_id: str) -> Path:
    item = db.get_item(conn, item_id)
    path = item_path(item["video_id"])
    path.parent.mkdir(parents=True, exist_ok=True)
    tx = transcripts.get(conn, item_id)
    has_tx = bool(tx and tx["source"] == "captions" and tx["lines"])
    if has_tx:
        transcript_path(item["video_id"]).write_text(render_transcript(item, tx["lines"]))
    path.write_text(
        render(item, db.item_sources(conn, item_id), tagging.item_tags(conn, item_id), has_tx)
    )
    return path
