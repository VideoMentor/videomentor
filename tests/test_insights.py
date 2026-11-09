"""Tags, insights and next-up endpoints."""

import json
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from conftest import add
from videomentor import actions, db, library, tagging
from videomentor.api import create_app
from videomentor.config import Settings


@pytest.fixture
def client(conn):
    app = create_app(Settings(pair_code="TESTCODE"), run_worker=False)
    with TestClient(app) as c:
        c.headers["Authorization"] = "Bearer TESTCODE"
        yield c


def ago(**kw) -> str:
    return (datetime.now(UTC) - timedelta(**kw)).isoformat(timespec="seconds")


def video(
    conn,
    vid,
    *,
    tags=(),
    status="inbox",
    signal=None,
    duration=None,
    skills=None,
    words=None,
    steps=(),
    source=None,
):
    item = add(conn, vid)
    tagging.set_tags(conn, item, list(tags))
    conn.execute(
        "UPDATE items SET status = ?, signal = ?, duration_s = ? WHERE id = ?",
        (status, signal, duration, item),
    )
    if skills is not None:
        analysis = {
            "skills": skills,
            "key_points": ["a", "b"],
            "frameworks": [{"name": "f"}],
            "takeaways": ["t"],
            "try_this_week": list(steps),
            "signal": signal or 3,
        }
        conn.execute(
            "UPDATE items SET analysis_status = 'done', analysis = ?, analyzed_at = ?,"
            " analysis_queued_at = ? WHERE id = ?",
            (json.dumps(analysis), ago(hours=1), ago(hours=3), item),
        )
    if words is not None:
        lines = [[i, " ".join(["w"] * n)] for i, n in enumerate(words)]
        conn.execute(
            "INSERT INTO transcripts (item_id, source, lines, fetched_at) VALUES (?, 'captions', ?, ?)",
            (item, json.dumps(lines), db.now()),
        )
    if source:
        conn.execute(
            "INSERT OR IGNORE INTO item_sources (item_id, source, first_seen) VALUES (?, ?, ?)",
            (item, source, db.now()),
        )
    conn.commit()
    return item


@pytest.fixture
def lib(conn):
    ids = {
        "k1": video(
            conn,
            "k1",
            tags=["Pricing", "sales"],
            status="kept",
            signal=5,
            duration=600,
            skills=["Negotiation", "Sales"],
            words=[3, 4],
            steps=["Raise a price", "Ask for the sale"],
        ),
        "k2": video(
            conn,
            "k2",
            tags=["pricing"],
            status="kept",
            signal=3,
            duration=999_999,
            skills=["Sales"],
        ),
        "i1": video(conn, "i1", tags=["pricing"], signal=4, duration=1200),
        "i2": video(conn, "i2", tags=["sales"], signal=4, duration=300),
        "i3": video(conn, "i3", tags=["cooking"], signal=5, duration=100),
        "a1": video(conn, "a1", tags=["Pricing"], status="archived", signal=1),
    }
    actions.collect(conn)
    return ids


# --- /api/tags ----------------------------------------------------------------


def test_tags_counts_case_insensitive_and_sorted(client, lib):
    tags = client.get("/api/tags").json()["tags"]
    assert [t["tag"].lower() for t in tags] == ["pricing", "sales", "cooking"]
    p = tags[0]
    assert (p["total"], p["kept"], p["inbox"], p["archived"], p["analyzed"]) == (4, 2, 1, 1, 2)
    assert p["avg_signal"] == pytest.approx((5 + 3 + 4 + 1) / 4)
    assert p["minutes"] == 10  # the 999,999 s duration is ignored
    assert set(p) == {
        "tag",
        "total",
        "kept",
        "inbox",
        "archived",
        "analyzed",
        "avg_signal",
        "minutes",
    }


def test_tags_requires_auth(conn):
    with TestClient(create_app(Settings(pair_code="TESTCODE"), run_worker=False)) as c:
        for path in ("/api/tags", "/api/tags/x/items", "/api/insights", "/api/next-up"):
            assert c.get(path).status_code == 401


# --- /api/tags/{tag}/items -------------------------------------------------------


def test_tag_items_default_kept(client, lib):
    r = client.get("/api/tags/PRICING/items").json()
    assert r["tag"].lower() == "pricing"
    assert [i["id"] for i in r["items"]] == [lib["k1"], lib["k2"]]
    assert r["summary"] == {"count": 2, "minutes": 10, "analyzed": 2}
    k1, k2 = r["items"]
    assert set(k1) == {
        "id",
        "title",
        "channel",
        "status",
        "signal",
        "duration_s",
        "words",
        "notes",
        "actions_open",
        "actions_done",
        "added_at",
        "analyzed_at",
    }
    assert (k1["words"], k1["notes"], k1["actions_open"], k1["actions_done"]) == (7, 4, 2, 0)
    assert k2["duration_s"] is None and k2["words"] is None


def test_tag_items_status_filter(client, lib):
    assert [
        i["id"] for i in client.get("/api/tags/pricing/items?status=inbox").json()["items"]
    ] == [lib["i1"]]
    assert len(client.get("/api/tags/pricing/items?status=all").json()["items"]) == 4
    assert client.get("/api/tags/pricing/items?status=bogus").status_code == 422
    empty = client.get("/api/tags/nope/items").json()
    assert empty["items"] == [] and empty["summary"]["count"] == 0


def test_tag_items_with_slash_and_history_still_routes(client, conn):
    a = video(conn, "s1", tags=["9/11"], status="kept")
    assert [i["id"] for i in client.get("/api/tags/9%2F11/items").json()["items"]] == [a]
    assert client.get("/api/tags/pricing/history").status_code == 200


def test_notes_zero_without_analysis(client, conn):
    video(conn, "n1", tags=["x"], status="kept")
    assert client.get("/api/tags/x/items").json()["items"][0]["notes"] == 0


# --- /api/insights ---------------------------------------------------------------


def test_insights_shape_and_skills(client, lib):
    r = client.get("/api/insights").json()
    assert set(r) >= {
        "skills",
        "funnel",
        "signal_keep",
        "signal_keep_clean",
        "sources",
        "latency",
        "usage",
        "inbox_by_tag",
    }
    skills = {s["skill"]: s for s in r["skills"]}
    assert skills["Sales"]["kept"] == 2 and skills["Sales"]["analyzed"] == 2
    assert skills["Negotiation"]["actions_open"] == 2
    assert skills["Sales"]["avg_signal"] == pytest.approx(4.0)
    assert skills["Sales"]["minutes"] == 10
    assert set(skills["Sales"]) == {
        "skill",
        "kept",
        "analyzed",
        "avg_signal",
        "minutes",
        "actions_open",
        "actions_done",
    }


def test_insights_funnel_and_signal_keep(client, conn, lib):
    a = video(conn, "d1", signal=2)
    b = video(conn, "d2", signal=2)
    library.decide(conn, a, "keep", "c1")
    library.decide(conn, b, "archive", "c2")
    library.undo(conn)  # undoes the archive
    conn.execute("UPDATE items SET signal = 5 WHERE id = ?", (a,))  # rescored after keep
    conn.commit()
    r = client.get("/api/insights").json()
    f = r["funnel"]
    assert (f["kept"], f["archived"], f["analyzed"], f["analysis_failed"]) == (3, 1, 2, 0)
    assert f["inbox"] == 4
    assert f["decisions_7d"] == 2 and f["undo_rate"] == pytest.approx(0.5)
    by_signal = {s["signal"]: s for s in r["signal_keep"]}
    assert by_signal[5]["kept"] == 2 and by_signal[1]["archived"] == 1
    assert by_signal[1]["rate"] == 0
    clean = {s["signal"]: s for s in r["signal_keep_clean"]}
    assert clean == {2: {"signal": 2, "kept": 1, "archived": 0, "rate": 1.0}}


def test_insights_sources_latency_inbox_by_tag(client, conn):
    video(conn, "s1", status="kept", source="playlist:PL1", skills=["Sales"], tags=["t"])
    video(conn, "s2", status="archived", source="playlist:PL1", tags=["t"])
    video(conn, "s3", tags=["t"], signal=4)
    video(conn, "s4", tags=["t", "u"], signal=2)
    r = client.get("/api/insights").json()
    src = {s["source"]: s for s in r["sources"]}
    assert src["playlist:PL1"]["kept"] == 1 and src["playlist:PL1"]["rate"] == 0.5
    assert src["youtube:watch_later"]["kept"] == 1
    assert r["latency"]["queue_to_notes_h"] == pytest.approx(2.0)
    assert r["inbox_by_tag"][0] == {"tag": "t", "inbox": 2, "avg_signal": 3.0}


def test_insights_usage(client, conn):
    conn.execute(
        "INSERT INTO llm_calls (at, step, ok, input_tokens, output_tokens, cost_usd)"
        " VALUES (?, 'prep', 1, 10, 5, 0.5)",
        (db.now(),),
    )
    conn.commit()
    u = client.get("/api/insights").json()["usage"]
    assert u["total"]["calls"] == 1 and u["last_7d"]["cost_usd"] == 0.5
    assert u["by_step"][0]["step"] == "prep"


def test_insights_empty_library(client, conn):
    r = client.get("/api/insights").json()
    assert r["funnel"]["undo_rate"] is None
    assert r["latency"] == {"queue_to_notes_h": None, "save_to_notes_h": None}
    assert r["signal_keep"] == [] and r["sources"] == [] and r["inbox_by_tag"] == []


# --- /api/next-up ----------------------------------------------------------------


def test_next_up_watch(client, lib):
    r = client.get("/api/next-up").json()
    assert r["mode"] == "watch"
    # Highest signal (5), then shortest: i3.
    assert r["item"]["id"] == lib["i3"]


def test_next_up_watch_by_skill(client, lib):
    # Negotiation's kept video k1 has tags Pricing and sales: i1 and i2 share them, i3 doesn't.
    r = client.get("/api/next-up?mode=watch&skill=negotiation").json()
    assert r["item"]["id"] == lib["i2"]  # signal 4 like i1, but shorter
    assert client.get("/api/next-up?skill=Nothing").json()["item"] is None


def test_next_up_apply(client, conn, lib):
    r = client.get("/api/next-up?mode=apply").json()
    assert r["mode"] == "apply"
    a = r["action"]
    assert a["item_id"] == lib["k1"] and a["item_title"] == "Video k1"
    assert a["text"] == "Raise a price" and a["status"] == "open"
    actions.update(conn, a["id"], status="done")
    assert client.get("/api/next-up?mode=apply").json()["action"]["text"] == "Ask for the sale"


def test_next_up_apply_empty_and_bad_mode(client, conn):
    assert client.get("/api/next-up?mode=apply").json() == {"mode": "apply", "action": None}
    assert client.get("/api/next-up?mode=watch").json() == {"mode": "watch", "item": None}
    assert client.get("/api/next-up?mode=bogus").status_code == 422
