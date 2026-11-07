"""Subject tags: 3 to 8 words or short phrases per video, from a shared vocabulary.

Tags are separate from card-prep topics (1 to 3 labels used for grouping). The
pass reuses tags already in the library before inventing new ones, so the list
stays small enough to browse.
"""

from __future__ import annotations

import re
import sqlite3

from . import db, llm

MIN_TAGS = 3
MAX_TAGS = 8
MAX_TAG_LEN = 40
VOCAB_IN_PROMPT = 200

SYSTEM = f"""You tag YouTube videos one person saved, so they can later find \
everything they have seen on a subject.
For each video, using only the metadata given, return {MIN_TAGS} to {MAX_TAGS} tags:
- What the video is about: subjects, skills, methods, tools, products, people, \
industries. Business and practical angles matter most (for example "pricing", \
"cold outreach", "negotiation tactics", "Claude Code", "hiring").
- One to four words each. Lowercase, except proper nouns and acronyms.
- No generic tags ("video", "youtube", "tutorial", "interesting") and no channel names.
- Reuse a tag from the existing list whenever it fits, spelled exactly the same. \
Only add a new tag when none fits.
Return one result per input id, in the same order."""

SCHEMA = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "tags": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["id", "tags"],
            },
        }
    },
    "required": ["items"],
}


def normalize(raw: list[str], vocab: dict[str, str]) -> list[str]:
    """Clean, dedupe (ignoring case), map to existing spellings, cap the count."""
    out: list[str] = []
    seen: set[str] = set()
    for tag in raw:
        if not isinstance(tag, str):
            continue
        clean = re.sub(r"\s+", " ", tag).strip().strip("#").strip()[:MAX_TAG_LEN].strip()
        key = clean.lower()
        if not clean or key in seen:
            continue
        seen.add(key)
        out.append(vocab.get(key, clean))
        if len(out) == MAX_TAGS:
            break
    return out


def vocabulary(conn: sqlite3.Connection, limit: int | None = None) -> list[tuple[str, int]]:
    """Tags in use, most used first."""
    sql = "SELECT tag, COUNT(*) AS n FROM item_tags GROUP BY tag ORDER BY n DESC, tag"
    if limit:
        sql += f" LIMIT {int(limit)}"
    return [(r["tag"], r["n"]) for r in conn.execute(sql)]


def vocab_map(conn: sqlite3.Connection) -> dict[str, str]:
    """lowercase name -> spelling to use: tags in use, plus merged-away aliases."""
    out = {tag.lower(): tag for tag, _ in vocabulary(conn)}
    for r in conn.execute("SELECT alias, tag FROM tag_aliases"):
        out[r["alias"].lower()] = r["tag"]
    return out


def item_tags(conn: sqlite3.Connection, item_id: str) -> list[str]:
    rows = conn.execute("SELECT tag FROM item_tags WHERE item_id = ? ORDER BY rowid", (item_id,))
    return [r["tag"] for r in rows]


def set_tags(conn: sqlite3.Connection, item_id: str, tags: list[str]) -> None:
    conn.execute("DELETE FROM item_tags WHERE item_id = ?", (item_id,))
    for tag in tags:
        conn.execute("INSERT OR IGNORE INTO item_tags (item_id, tag) VALUES (?, ?)", (item_id, tag))


def pending(conn: sqlite3.Connection, limit: int) -> list[dict]:
    """Untagged videos with metadata. Inbox first so the deck fills fastest."""
    rows = conn.execute(
        "SELECT * FROM items WHERE tag_status = 'pending' AND available = 1"
        " AND enrich_status IN ('done', 'failed')"
        " ORDER BY status = 'inbox' DESC, added_at DESC LIMIT ?",
        (limit,),
    )
    return [db.row_to_dict(r) for r in rows]


def tag_batch(conn: sqlite3.Connection, items: list[dict], model: str) -> int:
    """Tag a batch with one LLM call. Items missing from the reply are marked failed."""
    from .prep import _describe  # prep imports library, which imports this module

    if not items:
        return 0
    vocab_list = vocabulary(conn, VOCAB_IN_PROMPT)
    vocab = vocab_map(conn)
    prompt = ""
    if vocab_list:
        prompt += "Existing tags (reuse when they fit): " + ", ".join(t for t, _ in vocab_list)
        prompt += "\n\n"
    prompt += "\n\n".join(_describe(i) for i in items)
    out = llm.structured(prompt, system=SYSTEM, schema=SCHEMA, model=model)
    by_id = {r.get("id"): r for r in out.get("items", []) if isinstance(r, dict)}
    done = 0
    for item in items:
        tags = normalize((by_id.get(item["id"]) or {}).get("tags") or [], vocab)
        if not tags:
            conn.execute("UPDATE items SET tag_status = 'failed' WHERE id = ?", (item["id"],))
            continue
        set_tags(conn, item["id"], tags)
        vocab.update({t.lower(): t for t in tags})
        conn.execute(
            "UPDATE items SET tag_status = 'done', updated_at = ? WHERE id = ?",
            (db.now(), item["id"]),
        )
        done += 1
    conn.commit()
    return done
