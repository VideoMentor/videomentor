"""Actions: "try this week" items from analyses, collected into one checklist."""

import json

from fastapi.testclient import TestClient

from conftest import add
from videomentor import actions, db
from videomentor.api import create_app
from videomentor.config import Settings


def analyzed(conn, vid, steps, status="kept", moment=None, signal=4, category="learning"):
    item = add(conn, vid, category=category)
    conn.execute(
        "UPDATE items SET status = ?, analysis_status = 'done', analysis = ? WHERE id = ?",
        (
            status,
            json.dumps({"try_this_week": steps, "key_moment": moment, "signal": signal}),
            item,
        ),
    )
    conn.commit()
    return item


def test_collect_is_idempotent_and_skips_archived(conn):
    a = analyzed(conn, "a", ["Write your blame reply", "Slow down"])
    analyzed(conn, "b", ["Archived idea"], status="archived")
    assert actions.collect(conn) == 2
    assert actions.collect(conn) == 0
    rows = actions.list_actions(conn, "open")
    assert [r["text"] for r in rows] == ["Write your blame reply", "Slow down"]
    assert rows[0]["item"]["id"] == a and rows[0]["item"]["title"] == "Video a"


def test_reanalysis_keeps_done_state_and_adds_new_steps(conn):
    a = analyzed(conn, "a", ["One", "Two"])
    actions.collect(conn)
    first = actions.list_actions(conn, "open")[0]
    actions.update(conn, first["id"], status="done", note="did it Tuesday")
    conn.execute(
        "UPDATE items SET analysis = ? WHERE id = ?",
        (json.dumps({"try_this_week": ["One", "Three"]}), a),
    )
    actions.collect(conn)
    done = actions.list_actions(conn, "done")
    assert [(r["text"], r["note"]) for r in done] == [("One", "did it Tuesday")]
    assert [r["text"] for r in actions.list_actions(conn, "open")] == ["Two", "Three"]


def test_counts_and_reopen(conn):
    analyzed(conn, "a", ["One", "Two", "Three"])
    actions.collect(conn)
    one, two, three = actions.list_actions(conn, "open")
    actions.update(conn, one["id"], status="done")
    actions.update(conn, two["id"], status="skipped")
    assert actions.counts(conn) == {"open": 1, "done": 1, "skipped": 1, "done_this_week": 1}
    actions.update(conn, one["id"], status="open")
    assert actions.counts(conn)["open"] == 2
    assert db.get_item(conn, "yt:a")


def test_api(conn):
    analyzed(conn, "a", ["One"], moment={"t": 242, "label": "the anchor"})
    with TestClient(create_app(Settings(pair_code="T"), run_worker=False)) as c:
        c.headers["Authorization"] = "Bearer T"
        r = c.get("/api/actions").json()  # collects on read
        assert r["counts"]["open"] == 1
        (row,) = r["actions"]
        assert row["item"]["key_moment"] == {"t": 242, "label": "the anchor"}
        r = c.post(f"/api/actions/{row['id']}", json={"status": "done", "note": "ok"}).json()
        assert r["status"] == "done" and r["done_at"]
        assert c.get("/api/actions", params={"status": "done"}).json()["actions"][0]["note"] == "ok"
        assert c.post("/api/actions/999", json={"status": "done"}).status_code == 404
        assert c.post(f"/api/actions/{row['id']}", json={"status": "bogus"}).status_code == 422


def test_low_signal_and_music_are_left_out_and_tidied(conn):
    analyzed(conn, "good", ["Real step"])
    analyzed(conn, "low", ["Pick a video with a transcript instead"], signal=1)
    analyzed(conn, "song", ["Listen as a break"], category="music")
    analyzed(conn, "later", ["Will be archived", "Noted one"])
    actions.collect(conn)
    texts = [r["text"] for r in actions.list_actions(conn, "open")]
    assert texts == ["Real step", "Will be archived", "Noted one"]
    noted = actions.list_actions(conn, "open")[2]
    actions.update(conn, noted["id"], note="keep this")
    conn.execute("UPDATE items SET status = 'archived' WHERE id = 'yt:later'")
    actions.collect(conn)
    assert [r["text"] for r in actions.list_actions(conn, "open")] == ["Real step", "Noted one"]
