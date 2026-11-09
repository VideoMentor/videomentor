"""Deep analysis through a business lens: core idea, frameworks, actions, skills."""

from __future__ import annotations

import sqlite3

from . import db, llm, markdown, tagging, transcripts
from .library import dumps
from .sources import youtube

MAX_TRANSCRIPT_CHARS = 150_000

# 2: business lens. Older analyses are re-queued by `vm analyze --upgrade`.
ANALYSIS_VERSION = 2


def system(skills: list[str], signal_rules: str) -> str:
    return f"""You turn a YouTube video into business training notes for one person who \
wants to become a more effective business person. Their skill map: {", ".join(skills)}.
Be specific and faithful to the video; never invent content. If only metadata is \
available (no transcript), say so in the summary and keep every field short and \
clearly tentative.
- core_idea: the one idea worth remembering, in one sentence.
- summary: 2 to 4 sentences on what the video covers and its main argument.
- key_points: 3 to 8 concrete points, each one sentence.
- frameworks: named models, methods or step sequences the video teaches (name + how \
to use it in one sentence). Empty if there are none; don't force it.
- takeaways: 2 to 6 things to apply or remember, phrased as actions.
- try_this_week: 1 to 3 small, specific actions they could do in the next 7 days, \
drawn from this video's content. Leave it empty when the video has nothing to apply \
(music, entertainment, news). Never suggest finding or watching another video.
- moments: 3 to 8 timestamped moments worth jumping to (t = seconds from start, \
label = a few words, tag = the one given tag it is most about, if any).
- key_moment: the single moment where the core idea lands (t + label); t = -1 if \
there isn't one.
- skills: which skills from the skill map this builds (exact names, 0 to 3).
- useful_for: who gets the most from it, in a phrase.
- signal: 1 to 5, following these rules:
{signal_rules}
  signal_reason: under 100 characters.
- learnings: 2 to 6 takeaways to remember (kept for older screens).
- curriculum_topic: the single topic this belongs under (Title Case, 1 to 4 words).
Only use timestamps present in the transcript or chapters. Use the video's tags as \
the vocabulary for what it covers, so notes line up with the rest of the library."""


_MOMENT = {
    "type": "object",
    "properties": {
        "t": {"type": "integer"},
        "label": {"type": "string"},
        "tag": {"type": "string"},
    },
    "required": ["t", "label"],
}
_STRINGS = {"type": "array", "items": {"type": "string"}}

SCHEMA = {
    "type": "object",
    "properties": {
        "core_idea": {"type": "string"},
        "summary": {"type": "string"},
        "key_points": _STRINGS,
        "frameworks": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"name": {"type": "string"}, "how": {"type": "string"}},
                "required": ["name", "how"],
            },
        },
        "takeaways": _STRINGS,
        "try_this_week": _STRINGS,
        "moments": {"type": "array", "items": _MOMENT},
        "key_moment": _MOMENT,
        "skills": _STRINGS,
        "useful_for": {"type": "string"},
        "signal": {"type": "integer"},
        "signal_reason": {"type": "string"},
        "learnings": _STRINGS,
        "curriculum_topic": {"type": "string"},
    },
    "required": [
        "core_idea",
        "summary",
        "key_points",
        "frameworks",
        "takeaways",
        "try_this_week",
        "moments",
        "key_moment",
        "skills",
        "useful_for",
        "signal",
        "signal_reason",
        "learnings",
        "curriculum_topic",
    ],
}


def _real_time(t: object, anchors: list[int], slack: int = 30) -> bool:
    """True when t is within `slack` seconds of a caption line or chapter start."""
    return isinstance(t, int) and any(abs(t - a) <= slack for a in anchors)


def _clean(result: dict, skills: list[str], anchors: list[int]) -> dict:
    """Keep only skills from the map and timestamps that exist in the video."""
    by_lower = {s.lower(): s for s in skills}
    result["skills"] = [
        by_lower[s.lower()] for s in result.get("skills") or [] if s.lower() in by_lower
    ][:3]
    km = result.get("key_moment")
    if not isinstance(km, dict) or not isinstance(km.get("t"), int) or km["t"] < 0:
        result["key_moment"] = None
    if anchors:
        result["moments"] = [
            m for m in result.get("moments") or [] if _real_time(m.get("t"), anchors)
        ]
        if result["key_moment"] and not _real_time(result["key_moment"]["t"], anchors):
            result["key_moment"] = None
    from .scoring import clamp

    result["signal"] = clamp(result.get("signal"))
    result["version"] = ANALYSIS_VERSION
    return result


def queue_upgrades(conn: sqlite3.Connection) -> int:
    """Re-queue kept videos analyzed by an older version of the prompt."""
    return conn.execute(
        "UPDATE items SET analysis_status = 'queued', analysis_queued_at = ? WHERE status = 'kept'"
        " AND analysis_status = 'done'"
        " AND COALESCE(json_extract(analysis, '$.version'), 1) < ?",
        (db.now(), ANALYSIS_VERSION),
    ).rowcount


def stamp(seconds: int) -> str:
    h, rem = divmod(int(seconds), 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def format_transcript(lines: list[tuple[int, str]], window: int = 30) -> str:
    """Merge caption lines into ~30-second paragraphs, each led by its timestamp."""
    paragraphs: list[str] = []
    start, buf = None, []
    for t, text in lines:
        if start is None:
            start = t
        if t - start >= window and buf:
            paragraphs.append(f"[{stamp(start)} = {start}s] " + " ".join(buf))
            start, buf = t, []
        buf.append(text)
    if buf:
        paragraphs.append(f"[{stamp(start)} = {start}s] " + " ".join(buf))
    text = "\n".join(paragraphs)
    if len(text) > MAX_TRANSCRIPT_CHARS:
        # Keep the opening and closing, which carry the framing and conclusions.
        half = MAX_TRANSCRIPT_CHARS // 2
        text = text[:half] + "\n[... middle of transcript omitted ...]\n" + text[-half:]
    return text


def next_item(conn: sqlite3.Connection) -> dict | None:
    row = conn.execute(
        "SELECT * FROM items WHERE analysis_status = 'queued' AND status = 'kept'"
        " ORDER BY priority DESC, analysis_queued_at ASC LIMIT 1"
    ).fetchone()
    return db.row_to_dict(row) if row else None


def analyze_item(
    conn: sqlite3.Connection,
    item: dict,
    *,
    chrome_profile: str,
    model: str,
    skills: list[str] | None = None,
    signal_rules: str | None = None,
) -> dict:
    if skills is None or signal_rules is None:
        from .config import load_settings
        from .scoring import rules

        s = load_settings()
        skills = s.skill_map if skills is None else skills
        signal_rules = (
            rules(s.signal_areas, s.signal_guidance) if signal_rules is None else signal_rules
        )
    item_id = item["id"]
    conn.execute("UPDATE items SET analysis_status = 'running' WHERE id = ?", (item_id,))
    conn.commit()
    try:
        try:
            lines = youtube.fetch_transcript(item["video_id"], chrome_profile)
        except Exception:  # noqa: BLE001 - captions are optional; fall back to metadata
            lines = None
        else:
            transcripts.save(conn, item_id, lines)
            conn.commit()
        parts = [
            f"Title: {item.get('title')}",
            f"Channel: {item.get('channel')}",
            f"Tags: {', '.join(tagging.item_tags(conn, item_id)) or 'none yet'}",
            f"Length: {stamp(item['duration_s']) if item.get('duration_s') else 'unknown'}",
        ]
        if item.get("chapters"):
            parts.append(
                "Chapters:\n" + "\n".join(f"{c['t']}s {c['label']}" for c in item["chapters"])
            )
        parts.append(f"Description:\n{(item.get('description') or '')[:3000]}")
        if lines:
            parts.append("Transcript:\n" + format_transcript(lines))
        else:
            parts.append("Transcript: none available.")
        result = llm.structured(
            "\n\n".join(parts),
            system=system(skills, signal_rules),
            schema=SCHEMA,
            model=model,
            step="analyze",
            item_id=item_id,
            effort="medium",
        )
        anchors = [t for t, _ in lines or []] + [c["t"] for c in item.get("chapters") or []]
        result = _clean(result, skills, anchors)
        result["transcript_source"] = "captions" if lines else "none"
        conn.execute(
            "UPDATE items SET analysis = ?, analysis_status = 'done', analysis_error = NULL,"
            " analyzed_at = ?, ready_seen = 0, updated_at = ? WHERE id = ?",
            (dumps(result), db.now(), db.now(), item_id),
        )
        if result["signal"] is not None:
            conn.execute(
                "UPDATE items SET signal = ?, signal_reason = ?, signal_source = 'analysis',"
                " signal_status = 'done' WHERE id = ?",
                (result["signal"], (result.get("signal_reason") or "")[:120], item_id),
            )
        conn.commit()
    except Exception as e:
        conn.execute(
            "UPDATE items SET analysis_status = 'failed', analysis_error = ? WHERE id = ?",
            (str(e)[:1000], item_id),
        )
        conn.commit()
        raise
    finally:
        markdown.write_item(conn, item_id)
    return result
