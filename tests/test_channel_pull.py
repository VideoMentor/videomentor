"""Channel pulls: newest N, oldest N or a date range from a channel's uploads."""

import json
import time

import pytest
from fastapi.testclient import TestClient

from conftest import add
from videomentor import channel_pull, db, library, youtube_api
from videomentor.api import create_app
from videomentor.config import Settings
from videomentor.sources import youtube
from videomentor.sources.youtube import PlaylistEntry

# Uploads, newest first, as playlistItems returns them: v9 (newest) .. v0 (oldest)
UPLOADS = [(f"v{i}", f"2026-0{1 + i % 9}-{10 + i:02d}T12:00:00Z") for i in range(10)][::-1]
SHORTS = [("s1", "2026-03-15T12:00:00Z"), ("s0", "2026-01-05T12:00:00Z")]
LIVES = [("l1", "2026-02-20T12:00:00Z")]
_by_date = lambda vs: sorted(vs, key=lambda v: v[1], reverse=True)  # noqa: E731
# UULF regular videos, UUSH Shorts, UULV lives; UU (checked last) is everything.
LISTS = {"UULF": UPLOADS, "UUSH": SHORTS, "UULV": LIVES, "UU": _by_date(UPLOADS + SHORTS + LIVES)}


@pytest.fixture
def api(monkeypatch):
    youtube_api.client_path().parent.mkdir(parents=True, exist_ok=True)
    youtube_api.client_path().write_text(
        json.dumps({"installed": {"client_id": "c", "client_secret": "s"}})
    )
    youtube_api._save_token(
        {"refresh_token": "r", "access_token": "t", "expires_at": time.time() + 999}
    )
    calls = []

    def get_json(url, token):
        calls.append(url)
        if "/channels?" in url:
            return 200, {
                "items": [
                    {
                        "id": "UCxxxxxxxxxxxxxxxxxxxxxx",
                        "snippet": {"title": "Lenny"},
                        "contentDetails": {"relatedPlaylists": {"uploads": "UUx"}},
                    }
                ]
            }
        page = 0 if "pageToken" not in url else int(url.split("pageToken=")[1].split("&")[0])
        playlist = url.split("playlistId=")[1].split("&")[0]
        source = LISTS.get(playlist[:4], LISTS["UU"] if playlist.startswith("UU") else [])
        chunk = source[page * 4 : page * 4 + 4]
        body = {
            "items": [
                {
                    "snippet": {"title": f"Title {v}", "resourceId": {"videoId": v}},
                    "contentDetails": {"videoId": v, "videoPublishedAt": d},
                }
                for v, d in chunk
            ]
        }
        if page * 4 + 4 < len(source):
            body["nextPageToken"] = str(page + 1)
        return 200, body

    monkeypatch.setattr(youtube_api, "_get_json", get_json)
    return calls


def ids(conn):
    return [
        r[0][3:]
        for r in conn.execute(
            "SELECT item_id FROM item_sources WHERE source = 'channel:UCxxxxxxxxxxxxxxxxxxxxxx' ORDER BY item_id"
        )
    ]


def test_newest_stops_paging_early(conn, api):
    out = channel_pull.pull(conn, "UCxxxxxxxxxxxxxxxxxxxxxx", "newest", count=3)
    assert out["added"] == 3 and out["channel"] == "Lenny"
    assert ids(conn) == ["v7", "v8", "v9"]
    assert sum("playlistItems" in u for u in api) == 1  # one page was enough


def test_oldest_reads_to_the_end(conn, api):
    channel_pull.pull(conn, "UCxxxxxxxxxxxxxxxxxxxxxx", "oldest", count=2)
    assert ids(conn) == ["v0", "v1"]


def test_date_range_inclusive(conn, api):
    lo, hi = UPLOADS[6][1][:10], UPLOADS[3][1][:10]  # v3 .. v6
    channel_pull.pull(conn, "UCxxxxxxxxxxxxxxxxxxxxxx", "range", start=lo, end=hi)
    assert ids(conn) == ["v3", "v4", "v5", "v6"]


def test_cap_and_validation(conn, api):
    assert channel_pull.pull(conn, "UCxxxxxxxxxxxxxxxxxxxxxx", "newest", count=999)["added"] == 10
    with pytest.raises(ValueError):
        channel_pull.pull(conn, "UCxxxxxxxxxxxxxxxxxxxxxx", "range", start="2026-05-01")
    with pytest.raises(ValueError):
        channel_pull.pull(conn, "UCxxxxxxxxxxxxxxxxxxxxxx", "sideways", count=3)


def test_already_saved_videos_are_not_duplicated(conn, api):
    add(conn, "v9")
    out = channel_pull.pull(conn, "UCxxxxxxxxxxxxxxxxxxxxxx", "newest", count=2)
    assert out["added"] == 2 and out["seen"] == 2  # v9 is already saved: skipped, so v8 and v7
    assert db.item_sources(conn, "yt:v9") == ["youtube:watch_later"]
    channel_pull.pull(
        conn, "UCxxxxxxxxxxxxxxxxxxxxxx", "range", start="2026-01-01", end="2026-01-31"
    )
    assert db.item_sources(conn, "yt:v9") == [
        "youtube:watch_later",
        "channel:UCxxxxxxxxxxxxxxxxxxxxxx",
    ]


def test_pulled_videos_stay_out_of_all_saves(conn, api):
    add(conn, "saved")
    channel_pull.pull(conn, "UCxxxxxxxxxxxxxxxxxxxxxx", "newest", count=2)
    conn.execute("UPDATE items SET prep_status = 'done', category = 'learning'")
    all_ids = [c["id"] for c in library.deck(conn, "main", 10, [], "all")]
    assert all_ids == ["yt:saved"]
    pulled = [c["id"] for c in library.deck(conn, "main", 10, [], "ch:UCxxxxxxxxxxxxxxxxxxxxxx")]
    assert pulled == ["yt:v8", "yt:v9"]  # newest posted first (v8 Sep, v9 Jan)
    assert library.card(conn, db.get_item(conn, "yt:v9"))["saved_in_labels"] == [
        "Pulled from Lenny"
    ]


def test_without_api_falls_back_to_newest_only(conn, monkeypatch):
    monkeypatch.setattr(
        youtube,
        "fetch_playlist",
        lambda pid, prof: (
            {"title": "Lenny"},
            [
                PlaylistEntry("n1", "One", "Lenny", "UCxxxxxxxxxxxxxxxxxxxxxx", 60, 1, True),
                PlaylistEntry("n2", "Two", "Lenny", "UCxxxxxxxxxxxxxxxxxxxxxx", 60, 2, True),
            ],
        ),
    )
    out = channel_pull.pull(conn, "UCxxxxxxxxxxxxxxxxxxxxxx", "newest", count=1, chrome_profile="P")
    assert out["added"] == 1 and out["via"] == "yt-dlp"
    with pytest.raises(channel_pull.NeedsSignIn):
        channel_pull.pull(conn, "UCxxxxxxxxxxxxxxxxxxxxxx", "oldest", count=1, chrome_profile="P")


def test_api_endpoints(conn, api):
    with TestClient(create_app(Settings(pair_code="T"), run_worker=False)) as c:
        c.headers["Authorization"] = "Bearer T"
        r = c.post(
            "/api/channel/pull",
            json={"channel_id": "UCxxxxxxxxxxxxxxxxxxxxxx", "mode": "newest", "count": 2},
        ).json()
        assert r["added"] == 2
        lst = c.get("/api/channel-pulls").json()["channels"]
        assert lst[0]["channel_id"] == "UCxxxxxxxxxxxxxxxxxxxxxx" and lst[0]["videos"] == 2
        assert (
            c.post(
                "/api/channel/pull",
                json={"channel_id": "UCxxxxxxxxxxxxxxxxxxxxxx", "mode": "range"},
            ).status_code
            == 422
        )
        assert (
            c.get("/api/deck", params={"source": "ch:UCxxxxxxxxxxxxxxxxxxxxxx"}).status_code == 200
        )


CH = "UCxxxxxxxxxxxxxxxxxxxxxx"


def test_video_with_no_sources_stays_in_all_saves(conn, api):
    add(conn, "orphan")
    conn.execute(
        "DELETE FROM item_sources WHERE item_id = 'yt:orphan'"
    )  # removed from its playlist
    channel_pull.pull(conn, CH, "newest", count=2)
    conn.execute("UPDATE items SET prep_status = 'done', category = 'learning'")
    assert [c["id"] for c in library.deck(conn, "main", 10, [], "all")] == ["yt:orphan"]
    counts = library.counts(conn)
    assert counts["pulled_inbox"] == 2


def test_saved_and_pulled_counts_as_a_save(conn, api):
    add(conn, "v9")
    channel_pull.pull(conn, CH, "newest", count=2)
    conn.execute("UPDATE items SET prep_status = 'done', category = 'learning'")
    assert "yt:v9" in [c["id"] for c in library.deck(conn, "main", 10, [], "all")]
    assert library.counts(conn)["pulled_inbox"] == 2  # v8 and v7; v9 is a save


def test_groups_stay_on_the_anchor_side(conn, api):
    add(conn, "saved")
    channel_pull.pull(conn, CH, "newest", count=3)
    conn.execute("UPDATE items SET topics = '[\"growth\"]', channel_id = ?", (CH,))
    group = library.create_group(conn, "yt:saved")
    members = {m["id"] for m in group.get("items", [])} - {"yt:saved"}
    assert not members & {"yt:v9", "yt:v8", "yt:v7"}


def test_repull_keeps_decisions(conn, api):
    channel_pull.pull(conn, CH, "newest", count=2)
    conn.execute("UPDATE items SET status = 'archived' WHERE id = 'yt:v9'")
    out = channel_pull.pull(conn, CH, "newest", count=2)
    assert out["added"] == 2  # the next two: v7 and v6
    assert ids(conn) == ["v6", "v7", "v8", "v9"]
    assert db.get_item(conn, "yt:v9")["status"] == "archived"
    assert db.item_sources(conn, "yt:v9") == [f"channel:{CH}"]


def test_rejects_bad_channel_ids_and_dates(conn, api):
    for bad in ("UCx", "x&foo=bar#", "@handle", "UC" + "x" * 30):
        with pytest.raises(ValueError):
            channel_pull.pull(conn, bad, "newest", count=3)
    with pytest.raises(ValueError):
        channel_pull.pull(conn, CH, "range", start="2026-99-99", end="2026-12-01")


def test_next_n_walks_back_through_the_channel(conn, api):
    channel_pull.pull(conn, CH, "newest", count=3)
    channel_pull.pull(conn, CH, "newest", count=3)
    assert ids(conn) == ["v4", "v5", "v6", "v7", "v8", "v9"]
    channel_pull.pull(conn, CH, "oldest", count=2)
    channel_pull.pull(conn, CH, "oldest", count=2)
    assert ids(conn) == ["v0", "v1", "v2", "v3", "v4", "v5", "v6", "v7", "v8", "v9"]


def test_shorts_and_lives_are_opt_in(conn, api):
    channel_pull.pull(conn, CH, "newest", count=200)
    assert not {"s0", "s1", "l1"} & set(ids(conn))
    assert api and all("UULF" in u or "/channels?" in u for u in api)
    channel_pull.pull(conn, CH, "newest", count=200, include_lives=True)
    assert set(ids(conn)) - {f"v{i}" for i in range(10)} == {"l1"}
    channel_pull.pull(conn, CH, "newest", count=200, include_shorts=True, include_lives=True)
    assert {"s0", "s1"} <= set(ids(conn))
    assert any("playlistId=UUxx" in u for u in api)  # both on: the full uploads list


def test_shorts_only_merge_in_date_order(conn, api):
    found = channel_pull._select(
        channel_pull.heapq.merge(
            iter([("a", None, "2026-03-01T00:00:00Z"), ("b", None, "2026-01-01T00:00:00Z")]),
            iter([("s", None, "2026-02-01T00:00:00Z")]),
            key=lambda v: v[2],
            reverse=True,
        ),
        "newest",
        3,
        None,
        None,
        set(),
    )
    assert [v[0] for v in found] == ["a", "s", "b"]


def test_undated_entries_are_dropped_and_dont_stall_a_merge(conn, monkeypatch):
    pages = {
        "UULFa": [("x", ""), ("r2", "2026-03-01T00:00:00Z"), ("r1", "2026-01-01T00:00:00Z")],
        "UUSHa": [("s1", "2026-02-01T00:00:00Z"), ("s0", "2025-01-01T00:00:00Z")],
    }

    def get(resource, params):
        if resource == "channels":
            return {"items": [{"snippet": {"title": "T"}}]}
        items = pages[params["playlistId"]]
        return {
            "items": [{"contentDetails": {"videoId": v, "videoPublishedAt": d}} for v, d in items]
        }

    monkeypatch.setattr(youtube_api, "get", get)
    budget = {"pages": 10, "cut": False}
    _, videos = channel_pull._uploads("UCa", True, False, budget)
    assert [v[0] for v in videos] == ["r2", "s1", "r1", "s0"]


def test_oldest_says_so_when_the_channel_is_too_big(conn, api, monkeypatch):
    monkeypatch.setattr(channel_pull, "MAX_PAGES", 1)
    with pytest.raises(channel_pull.TooBig):
        channel_pull.pull(conn, CH, "oldest", count=2)
