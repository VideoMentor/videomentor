import pytest

from conftest import add
from videomentor import db, library


def status(conn, item_id):
    return db.get_item(conn, item_id)["status"]


def test_keep_archive_prioritize_transitions(conn):
    a, b, c = add(conn, "aaaaaaaaaaa"), add(conn, "bbbbbbbbbbb"), add(conn, "ccccccccccc")
    library.decide(conn, a, "keep", "c1")
    library.decide(conn, b, "archive", "c2")
    library.decide(conn, c, "prioritize", "c3")
    ia, ib, ic = (db.get_item(conn, x) for x in (a, b, c))
    assert (ia["status"], ia["priority"], ia["analysis_status"]) == ("kept", 0, "queued")
    assert (ib["status"], ib["analysis_status"]) == ("archived", "none")
    assert (ic["status"], ic["priority"], ic["analysis_status"]) == ("kept", 1, "queued")


def test_decide_is_idempotent_on_client_id(conn):
    a = add(conn, "aaaaaaaaaaa")
    first = library.decide(conn, a, "keep", "same")
    second = library.decide(conn, a, "archive", "same")
    assert first["decision_id"] == second["decision_id"]
    assert status(conn, a) == "kept"
    assert conn.execute("SELECT COUNT(*) FROM decisions").fetchone()[0] == 1


def test_undo_latest_restores_state_and_logs(conn):
    a = add(conn, "aaaaaaaaaaa")
    library.decide(conn, a, "prioritize", "c1")
    out = library.undo(conn)
    item = db.get_item(conn, a)
    assert (item["status"], item["priority"], item["analysis_status"]) == ("inbox", 0, "none")
    assert out["items"][0]["id"] == a
    actions = [r["action"] for r in conn.execute("SELECT action FROM decisions ORDER BY id")]
    assert actions == ["prioritize", "undo"]
    # Undo again finds nothing left to undo.
    assert library.undo(conn)["undone"] == []


def test_undo_keeps_finished_analysis(conn):
    a = add(conn, "aaaaaaaaaaa")
    d = library.decide(conn, a, "keep", "c1")
    conn.execute("UPDATE items SET analysis_status = 'done' WHERE id = ?", (a,))
    library.undo(conn, d["decision_id"])
    assert db.get_item(conn, a)["analysis_status"] == "done"


def test_undo_of_older_decision_conflicts(conn):
    a = add(conn, "aaaaaaaaaaa")
    first = library.decide(conn, a, "keep", "c1")
    library.decide(conn, a, "archive", "c2")
    with pytest.raises(library.UndoConflict):
        library.undo(conn, first["decision_id"])


def test_unavailable_auto_archived_and_not_default_undo(conn):
    library.upsert_item(conn, "zzzzzzzzzzz", source="youtube:watch_later", available=False)
    item = db.get_item(conn, "yt:zzzzzzzzzzz")
    assert (item["status"], item["status_reason"]) == ("archived", "unavailable")
    assert library.undo(conn)["undone"] == []


def test_upsert_merges_sources_and_keeps_earliest_added(conn):
    library.upsert_item(conn, "aaaaaaaaaaa", source="youtube:watch_later", added_at="2026-05-01")
    new = library.upsert_item(conn, "aaaaaaaaaaa", source="safari", added_at="2025-01-01")
    assert new is False
    assert db.get_item(conn, "yt:aaaaaaaaaaa")["added_at"] == "2025-01-01"
    assert db.item_sources(conn, "yt:aaaaaaaaaaa") == ["youtube:watch_later", "safari"]


def test_deck_splits_main_and_music_and_orders_newest_first(conn):
    old = add(conn, "aaaaaaaaaaa", added="2025-01-01")
    new = add(conn, "bbbbbbbbbbb", added="2026-06-01")
    song = add(conn, "ccccccccccc", category="music")
    library.decide(conn, add(conn, "ddddddddddd"), "keep", "c1")
    assert [c["id"] for c in library.deck(conn, "main", 10, [])] == [new, old]
    assert [c["id"] for c in library.deck(conn, "music", 10, [])] == [song]
    assert [c["id"] for c in library.deck(conn, "main", 10, [new])] == [old]


def test_deck_includes_failed_prep_without_category(conn):
    library.upsert_item(conn, "eeeeeeeeeee", source="safari")
    conn.execute("UPDATE items SET prep_status = 'failed' WHERE id = 'yt:eeeeeeeeeee'")
    assert [c["id"] for c in library.deck(conn, "main", 10, [])] == ["yt:eeeeeeeeeee"]


def test_group_by_topic_and_channel_then_decide_and_undo_as_batch(conn):
    anchor = add(conn, "aaaaaaaaaaa", topics=["MCP", "Agents"], channel="Theo")
    both = add(conn, "bbbbbbbbbbb", topics=["MCP", "Agents"], channel="Other")
    chan = add(conn, "ccccccccccc", topics=["Cooking"], channel="Theo")
    add(conn, "ddddddddddd", topics=["Cooking"], channel="Nobody")
    out = library.create_group(conn, anchor)
    ids = [c["id"] for c in out["items"]]
    assert ids == [anchor, both, chan]
    assert out["group"]["basis"] == "topic"

    res = library.decide_group(conn, out["group"]["id"], "keep", "g1")
    assert len(res["decision_ids"]) == 3
    assert all(status(conn, i) == "kept" for i in ids)
    # Retrying the same group decision does nothing new.
    assert (
        library.decide_group(conn, out["group"]["id"], "keep", "g1")["decision_ids"]
        == res["decision_ids"]
    )
    undone = library.undo(conn)
    assert sorted(undone["undone"]) == sorted(res["decision_ids"])
    assert all(status(conn, i) == "inbox" for i in ids)


def test_group_skips_members_already_decided(conn):
    anchor = add(conn, "aaaaaaaaaaa", topics=["MCP"])
    other = add(conn, "bbbbbbbbbbb", topics=["MCP"])
    group = library.create_group(conn, anchor)
    library.decide(conn, other, "archive", "c1")
    res = library.decide_group(conn, group["group"]["id"], "keep", "g1")
    assert len(res["decision_ids"]) == 1
    assert status(conn, other) == "archived"


def test_ready_and_counts(conn):
    a = add(conn, "aaaaaaaaaaa")
    library.decide(conn, a, "prioritize", "c1")
    conn.execute("UPDATE items SET analysis_status = 'done', analysis = '{\"summary\": \"S\"}'")
    assert [c["id"] for c in library.ready(conn)] == [a]
    assert library.ready(conn)[0]["summary_short"] == "S"
    assert library.counts(conn)["ready"] == 1
    library.mark_seen(conn, a)
    assert library.ready(conn) == []


def test_watch_later_items_have_no_save_date_until_a_bookmark_supplies_one(conn):
    library.upsert_item(conn, "aaaaaaaaaaa", source="youtube:watch_later")
    assert library.card(conn, db.get_item(conn, "yt:aaaaaaaaaaa"))["added_at"] is None
    library.upsert_item(conn, "aaaaaaaaaaa", source="chrome:Default", added_at="2024-03-01")
    assert library.card(conn, db.get_item(conn, "yt:aaaaaaaaaaa"))["added_at"] == "2024-03-01"
