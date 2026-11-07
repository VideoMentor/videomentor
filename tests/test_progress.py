"""Progress and milestones for celebrations: counted on the server, each shown once."""

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from conftest import add
from videomentor import library, progress
from videomentor.api import create_app
from videomentor.config import Settings


def decide(conn, item_id, action, days_ago=0, cid=None):
    at = (datetime.now(UTC) - timedelta(days=days_ago)).isoformat(timespec="seconds")
    library.decide(conn, item_id, action, cid or f"{item_id}-{action}-{days_ago}", at)


def test_counts_hours_and_streak(conn):
    ids = [add(conn, f"v{i}") for i in range(12)]
    conn.execute("UPDATE items SET duration_s = 3600")
    for i, item in enumerate(ids[:11]):
        decide(conn, item, "keep" if i % 2 else "archive", days_ago=i % 3)
    library.mark_unavailable(conn, ids[11])  # automatic archive: not counted
    conn.commit()
    p = progress.summary(conn)
    assert p["decided"] == 11
    assert p["kept"] == 5 and p["archived"] == 6
    assert p["hours"] == 11.0
    assert p["streak_days"] == 3  # today, yesterday, the day before
    assert p["today"] >= 1


def test_undone_decisions_dont_count(conn):
    a = add(conn, "a")
    decide(conn, a, "keep")
    library.undo(conn)
    conn.commit()
    assert progress.summary(conn)["decided"] == 0


def test_streak_broken_by_a_missing_day(conn):
    a, b = add(conn, "a"), add(conn, "b")
    decide(conn, a, "keep", days_ago=0)
    decide(conn, b, "keep", days_ago=2)
    conn.commit()
    assert progress.summary(conn)["streak_days"] == 1


def test_milestones_show_only_the_highest_new_one_per_kind_then_never_again(conn):
    ids = [add(conn, f"v{i}") for i in range(26)]
    conn.execute("UPDATE items SET duration_s = 1800")  # 26 x 30 min = 13 hours
    for item in ids:
        decide(conn, item, "keep")
    conn.commit()
    new = progress.unseen(conn)
    assert [(m["kind"], m["value"]) for m in new] == [("videos", 25), ("hours", 10)]
    assert new[0]["label"] == "25 videos triaged"
    progress.mark_seen(conn, [m["id"] for m in new])
    assert progress.unseen(conn) == []
    # lower thresholds were marked too, so they never pop up later
    assert "videos-10" in progress.seen_ids(conn)


def test_api(conn):
    for i in range(10):
        decide(conn, add(conn, f"v{i}"), "keep")
    conn.commit()
    with TestClient(create_app(Settings(pair_code="T"), run_worker=False)) as c:
        c.headers["Authorization"] = "Bearer T"
        r = c.get("/api/progress").json()
        assert r["decided"] == 10 and [m["id"] for m in r["unseen"]] == ["videos-10"]
        assert c.post("/api/milestones/seen", json={"ids": ["videos-10"]}).json() == {"ok": True}
        assert c.get("/api/progress").json()["unseen"] == []
