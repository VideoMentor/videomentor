"""Tag merge list: fold near-duplicate tags into one, after you approve each merge.

An LLM drafts merges from the whole vocabulary; code checks them (only real tags,
no tag in two merges, no chains). Applying a merge rewrites item_tags, logs every
change so it can be undone, and records the folded names as aliases so future
tagging uses the kept name.
"""

from __future__ import annotations

import json
import sqlite3

from . import db, llm, tagging

SYSTEM = """You tidy the tag list of one person's YouTube learning library. An LLM \
tagged each video separately, so one subject often has several names, and most tags \
are used only once. Goal: about one tag per subject, so browsing by tag works. A \
result of roughly a third of the current count is about right.
Go through the WHOLE list and propose merges. Each merge keeps one existing tag and \
folds others into it:
- spelling, plural, hyphen and abbreviation variants ("no-code" -> "no code", \
"artificial intelligence" -> "AI")
- synonyms and near-synonyms ("workplace communication", "communication at work" -> \
"communication skills")
- narrow tags used once or twice into a broader existing tag that clearly covers them \
("local seo" -> "seo", "cold calling scripts" -> "cold calling")
Direction matters: always fold the narrower or rarer tag into the broader or more used \
one, never the reverse. Never fold a broad field into a sub-topic (not "machine \
learning" -> "llm").
Don't merge distinct skills or methods that someone would want to find on their own \
("negotiation tactics" stays separate from "persuasion"), different people, products, \
companies or events, or anything where the folded tag carries meaning the kept one \
would lose.
Use tag names exactly as given. Each tag appears in at most one merge, as keep or fold. \
Give a short reason per merge."""


SCHEMA = {
    "type": "object",
    "properties": {
        "merges": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "keep": {"type": "string"},
                    "fold": {"type": "array", "items": {"type": "string"}},
                    "reason": {"type": "string"},
                },
                "required": ["keep", "fold", "reason"],
            },
        }
    },
    "required": ["merges"],
}


def validate(raw: list[dict], counts: dict[str, int]) -> list[dict]:
    """Keep only merges of real tags, each tag used once, no chains."""
    real = {t.lower(): t for t in counts}
    used: set[str] = set()
    out = []
    for m in raw:
        keep = real.get(str(m.get("keep", "")).strip().lower())
        if not keep or keep.lower() in used:
            continue
        fold = []
        for f in m.get("fold") or []:
            name = real.get(str(f).strip().lower())
            # A folded tag used more than the kept one means the direction is backwards.
            if name and counts.get(name, 0) > counts.get(keep, 0):
                continue
            if name and name.lower() != keep.lower() and name.lower() not in used:
                if name not in fold:
                    fold.append(name)
        if not fold:
            continue
        used.add(keep.lower())
        used.update(f.lower() for f in fold)
        out.append({"keep": keep, "fold": fold, "reason": str(m.get("reason", ""))[:200]})
    return out


def save_proposals(conn: sqlite3.Connection, merges: list[dict]) -> int:
    """Replace unreviewed proposals with these."""
    conn.execute("DELETE FROM tag_merges WHERE status = 'proposed'")
    ts = db.now()
    for m in merges:
        conn.execute(
            "INSERT INTO tag_merges (keep, fold, reason, status, created_at)"
            " VALUES (?, ?, ?, 'proposed', ?)",
            (m["keep"], json.dumps(m["fold"], ensure_ascii=False), m["reason"], ts),
        )
    conn.commit()
    return len(merges)


def draft(conn: sqlite3.Connection, model: str) -> int:
    counts = dict(tagging.vocabulary(conn))
    prompt = "Tags (videos using each):\n" + "\n".join(f"{t} ({n})" for t, n in counts.items())
    out = llm.structured(prompt, system=SYSTEM, schema=SCHEMA, model=model, timeout=600)
    return save_proposals(conn, validate(out.get("merges") or [], counts))


def _row(conn: sqlite3.Connection, r: sqlite3.Row) -> dict:
    d = dict(r)
    d["fold"] = json.loads(d["fold"])
    marks = ",".join("?" * len(d["fold"]))
    d["videos"] = conn.execute(
        f"SELECT COUNT(DISTINCT item_id) FROM item_tags WHERE tag IN ({marks})", d["fold"]
    ).fetchone()[0]
    return d


def list_merges(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute("SELECT * FROM tag_merges ORDER BY status = 'proposed' DESC, id").fetchall()
    return [_row(conn, r) for r in rows]


def apply(conn: sqlite3.Connection, approve: list[int], reject: list[int]) -> dict:
    videos: set[str] = set()
    applied = 0
    for mid in approve:
        r = conn.execute(
            "SELECT * FROM tag_merges WHERE id = ? AND status = 'proposed'", (mid,)
        ).fetchone()
        if not r:
            continue
        keep, fold = r["keep"], json.loads(r["fold"])
        for tag in fold:
            for (item_id,) in conn.execute(
                "SELECT item_id FROM item_tags WHERE tag = ?", (tag,)
            ).fetchall():
                had_keep = conn.execute(
                    "SELECT 1 FROM item_tags WHERE item_id = ? AND tag = ?", (item_id, keep)
                ).fetchone()
                conn.execute("DELETE FROM item_tags WHERE item_id = ? AND tag = ?", (item_id, tag))
                conn.execute(
                    "INSERT OR IGNORE INTO item_tags (item_id, tag) VALUES (?, ?)", (item_id, keep)
                )
                conn.execute(
                    "INSERT INTO tag_merge_log (merge_id, item_id, old_tag, added_keep)"
                    " VALUES (?, ?, ?, ?)",
                    (mid, item_id, tag, int(not had_keep)),
                )
                videos.add(item_id)
            conn.execute(
                "INSERT OR REPLACE INTO tag_aliases (alias, tag) VALUES (?, ?)", (tag, keep)
            )
        conn.execute(
            "UPDATE tag_merges SET status = 'applied', applied_at = ? WHERE id = ?", (db.now(), mid)
        )
        applied += 1
    rejected = 0
    for mid in reject:
        rejected += conn.execute(
            "UPDATE tag_merges SET status = 'rejected' WHERE id = ? AND status = 'proposed'", (mid,)
        ).rowcount
    conn.commit()
    return {"applied": applied, "rejected": rejected, "videos": len(videos)}


def undo(conn: sqlite3.Connection, merge_id: int) -> dict:
    r = conn.execute("SELECT * FROM tag_merges WHERE id = ?", (merge_id,)).fetchone()
    if not r:
        raise KeyError(merge_id)
    if r["status"] == "applied":
        keep = r["keep"]
        for log in conn.execute(
            "SELECT * FROM tag_merge_log WHERE merge_id = ? ORDER BY rowid DESC", (merge_id,)
        ).fetchall():
            conn.execute(
                "INSERT OR IGNORE INTO item_tags (item_id, tag) VALUES (?, ?)",
                (log["item_id"], log["old_tag"]),
            )
            if log["added_keep"]:
                conn.execute(
                    "DELETE FROM item_tags WHERE item_id = ? AND tag = ?", (log["item_id"], keep)
                )
        conn.execute("DELETE FROM tag_merge_log WHERE merge_id = ?", (merge_id,))
        for tag in json.loads(r["fold"]):
            conn.execute("DELETE FROM tag_aliases WHERE alias = ? AND tag = ?", (tag, keep))
        conn.execute("UPDATE tag_merges SET status = 'undone' WHERE id = ?", (merge_id,))
        conn.commit()
    return _row(conn, conn.execute("SELECT * FROM tag_merges WHERE id = ?", (merge_id,)).fetchone())


def counts(conn: sqlite3.Connection) -> dict:
    rows = dict(conn.execute("SELECT status, COUNT(*) FROM tag_merges GROUP BY status").fetchall())
    return {"proposed": rows.get("proposed", 0), "applied": rows.get("applied", 0)}
