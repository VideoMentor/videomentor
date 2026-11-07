"""playlist list, enabled-playlist sync, deck sources, saved-in labels, Data API."""

import json
import threading
import time
import urllib.request
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient

from conftest import add
from videomentor import db, library, playlists, youtube_api
from videomentor.api import create_app
from videomentor.config import Settings
from videomentor.sources import youtube
from videomentor.sources.youtube import PlaylistEntry

S = Settings(pair_code="TESTCODE")


def entry(vid, pos, title=None):
    return PlaylistEntry(vid, title or f"Video {vid}", "Chan", "UC1", 60, pos, True)


@pytest.fixture
def client(conn):
    app = create_app(S, run_worker=False)
    with TestClient(app) as c:
        c.headers["Authorization"] = "Bearer TESTCODE"
        yield c


@pytest.fixture
def yt(monkeypatch):
    """A fake YouTube library with two playlists, a Mix and Watch Later."""
    feed = [("PLa", "Biz ideas"), ("WL", "Watch later"), ("RDmix", "Mix"), ("PLb", "Music")]
    details = {
        "PLa": {
            "title": "Biz ideas",
            "video_count": 2,
            "modified_date": "20261030",
            "owner": "Sample Channel",
            "owner_channel_id": "UCme",
            "visibility": "unlisted",
        },
        "PLb": {
            "title": "Music",
            "video_count": 1,
            "modified_date": "20240101",
            "owner": "Someone",
            "owner_channel_id": "UCx",
            "visibility": "public",
        },
    }
    contents = {"PLa": [entry("v1", 1), entry("v2", 2)], "PLb": [entry("v3", 1)]}
    calls = {"details": 0}

    def fetch_details(pid, profile):
        calls["details"] += 1
        return details[pid]

    monkeypatch.setattr(youtube, "fetch_playlist_feed", lambda profile: feed)
    monkeypatch.setattr(youtube, "fetch_playlist_details", fetch_details)
    monkeypatch.setattr(
        youtube, "fetch_playlist", lambda pid, profile: (details[pid], contents[pid])
    )
    return {"feed": feed, "details": details, "contents": contents, "calls": calls}


def prep_all(conn):
    conn.execute("UPDATE items SET prep_status = 'done', category = 'learning'")
    conn.commit()


# --- list and sync ------------------------------------------------------------


def test_refresh_list_skips_watch_later_and_mixes_and_caches_details(conn, yt):
    out = playlists.refresh_list(conn, S)
    assert out == {"listed": 2, "details_refreshed": 2}
    rows = playlists.list_playlists(conn)
    assert [r["id"] for r in rows] == ["PLa", "PLb"]
    assert rows[0]["video_count"] == 2 and rows[0]["modified_date"] == "20261030"
    assert rows[0]["enabled"] is False and rows[0]["newest_save"] is None
    playlists.refresh_list(conn, S)
    assert yt["calls"]["details"] == 2  # fresh details aren't fetched again
    yt["feed"].remove(("PLb", "Music"))
    playlists.refresh_list(conn, S)
    assert [r["id"] for r in playlists.list_playlists(conn)] == ["PLa"]


def test_sync_enabled_pulls_items_and_forgets_removed_ones(conn, yt):
    playlists.refresh_list(conn, S)
    playlists.set_enabled(conn, "PLa", True)
    out = playlists.sync_enabled(conn, S)
    assert out["new"] == 2 and out["seen"] == 2
    assert db.item_sources(conn, "yt:v1") == ["playlist:PLa"]
    assert library.saved_labels(conn, "yt:v1") == ["Biz ideas"]
    yt["contents"]["PLa"] = [entry("v2", 1)]
    playlists.sync_enabled(conn, S)
    row = playlists.playlist_row(conn, "PLa")
    assert row["synced"] == 1
    assert db.item_sources(conn, "yt:v1") == []
    assert db.get_item(conn, "yt:v1") is not None  # the video itself stays


def test_disabled_playlists_dont_sync(conn, yt):
    playlists.refresh_list(conn, S)
    assert playlists.sync_enabled(conn, S)["playlists"] == 0
    with pytest.raises(library.NotFound):
        playlists.set_enabled(conn, "nope", True)


def test_saved_labels_merge_sources(conn, yt):
    add(conn, "v1")  # already in Watch Later
    playlists.refresh_list(conn, S)
    playlists.set_enabled(conn, "PLa", True)
    playlists.sync_enabled(conn, S)
    card = library.card(conn, db.get_item(conn, "yt:v1"))
    assert card["saved_in_labels"] == ["Watch Later", "Biz ideas"]


# --- deck sources -------------------------------------------------------------


def test_deck_sources(conn, yt):
    add(conn, "w1", added="2026-01-05")
    playlists.refresh_list(conn, S)
    for pid in ("PLa", "PLb"):
        playlists.set_enabled(conn, pid, True)
    playlists.sync_enabled(conn, S)
    prep_all(conn)

    def ids(source):
        return [c["id"] for c in library.deck(conn, "main", 10, [], source)]

    assert set(ids("all")) == {"yt:w1", "yt:v1", "yt:v2", "yt:v3"}
    assert ids("wl") == ["yt:w1"]
    assert set(ids("playlists")) == {"yt:v1", "yt:v2", "yt:v3"}
    assert ids("pl:PLa") == ["yt:v1", "yt:v2"]  # stored order without API dates
    conn.execute(
        "UPDATE playlist_items SET added_at = '2026-10-01T00:00:00Z' WHERE item_id = 'yt:v2'"
    )
    conn.execute(
        "UPDATE playlist_items SET added_at = '2026-09-01T00:00:00Z' WHERE item_id = 'yt:v1'"
    )
    assert ids("pl:PLa") == ["yt:v2", "yt:v1"]  # newest save first once dates are known
    playlists.set_enabled(conn, "PLb", False)
    assert set(ids("playlists")) == {"yt:v1", "yt:v2"}


def test_api_deck_source_and_playlist_endpoints(client, conn, yt):
    playlists.refresh_list(conn, S)
    r = client.get("/api/playlists").json()
    assert [p["title"] for p in r["playlists"]] == ["Biz ideas", "Music"]
    assert r["youtube_api"]["state"] == "not_set_up"
    assert client.post("/api/playlists/PLa", json={"enabled": True}).json()["enabled"] is True
    assert client.post("/api/playlists/nope", json={"enabled": True}).status_code == 404
    assert client.get("/api/playlists/PLa").json()["title"] == "Biz ideas"
    playlists.sync_enabled(conn, S)
    prep_all(conn)
    cards = client.get("/api/deck", params={"source": "pl:PLa"}).json()["cards"]
    assert [c["id"] for c in cards] == ["yt:v1", "yt:v2"]
    assert cards[0]["saved_in_labels"] == ["Biz ideas"]
    assert client.get("/api/deck", params={"source": "bogus"}).status_code == 422
    status = client.get("/api/status").json()
    assert status["playlists_enabled"] == 1 and status["youtube_api"]["state"] == "not_set_up"


def test_channel_sheet_lists_videos(client, conn):
    add(conn, "a", channel="Lenny", added="2026-01-01")
    add(conn, "b", channel="Lenny", added="2026-02-01")
    r = client.get("/api/channel", params={"name": "Lenny"}).json()
    assert [i["id"] for i in r["items"]] == ["yt:b", "yt:a"]


# --- Data API -----------------------------------------------------------------


def write_client():
    youtube_api.client_path().parent.mkdir(parents=True, exist_ok=True)
    youtube_api.client_path().write_text(
        json.dumps(
            {
                "installed": {
                    "client_id": "cid",
                    "client_secret": "sec",
                    "auth_uri": "https://auth.example/auth",
                    "token_uri": "https://auth.example/token",
                }
            }
        )
    )


def test_api_states_and_login_flow(monkeypatch):
    assert youtube_api.state()["state"] == "not_set_up"
    write_client()
    assert youtube_api.state()["state"] == "signed_out"
    posted = {}

    def post(url, data):
        posted.update(data)
        return {"refresh_token": "r1", "access_token": "a1", "expires_in": 3600}

    monkeypatch.setattr(youtube_api, "_post_form", post)

    def open_url(url):
        q = parse_qs(urlparse(url).query)
        assert q["scope"] == [youtube_api.SCOPE] and q["code_challenge_method"] == ["S256"]
        back = f"{q['redirect_uri'][0]}/?code=abc&state={q['state'][0]}"

        def visit():
            time.sleep(0.05)
            urllib.request.urlopen(back, timeout=5).read()

        threading.Thread(target=visit, daemon=True).start()

    st = youtube_api.login(open_url, timeout_s=10)
    assert st["state"] == "ok"
    assert posted["code"] == "abc" and posted["grant_type"] == "authorization_code"
    assert posted["code_verifier"]
    assert oct(youtube_api.token_path().stat().st_mode)[-3:] == "600"
    assert youtube_api.access_token() == "a1"


def test_expired_sign_in_is_reported(monkeypatch):
    write_client()
    youtube_api._save_token({"refresh_token": "r1", "access_token": "old", "expires_at": 0})
    monkeypatch.setattr(youtube_api, "_post_form", lambda url, data: {"error": "invalid_grant"})
    with pytest.raises(youtube_api.SignInNeeded):
        youtube_api.access_token()
    assert youtube_api.state()["state"] == "expired"
    assert "vm youtube-login" in youtube_api.state()["message"]


def test_fill_api_dates(conn, yt, monkeypatch):
    write_client()
    youtube_api._save_token(
        {"refresh_token": "r1", "access_token": "tok", "expires_at": time.time() + 999}
    )

    def get_json(url, token):
        assert token == "tok"
        if "/playlists?" in url:
            return 200, {
                "items": [
                    {
                        "id": "PLa",
                        "snippet": {"publishedAt": "2021-03-04T00:00:00Z"},
                        "contentDetails": {"itemCount": 2},
                        "status": {"privacyStatus": "unlisted"},
                    }
                ]
            }
        if "pageToken" not in url:
            return 200, {
                "items": [
                    {
                        "contentDetails": {"videoId": "v1"},
                        "snippet": {"publishedAt": "2026-10-01T00:00:00Z"},
                    }
                ],
                "nextPageToken": "p2",
            }
        return 200, {
            "items": [
                {
                    "contentDetails": {"videoId": "v2"},
                    "snippet": {"publishedAt": "2026-10-02T00:00:00Z"},
                }
            ]
        }

    monkeypatch.setattr(youtube_api, "_get_json", get_json)
    playlists.refresh_list(conn, S)
    playlists.set_enabled(conn, "PLa", True)
    playlists.sync_enabled(conn, S)
    out = playlists.fill_api_dates(conn)
    assert out == {"created_dates": 1, "save_dates": 2, "errors": []}
    row = playlists.playlist_row(conn, "PLa")
    assert row["created_at"] == "2021-03-04T00:00:00Z"
    assert row["newest_save"] == "2026-10-02T00:00:00Z" and row["dates_known"] is True


def test_playlist_run_survives_failures(conn, monkeypatch):
    def boom(profile):
        raise RuntimeError("youtube down")

    monkeypatch.setattr(youtube, "fetch_playlist_feed", boom)
    out = playlists.run(conn, S)
    assert any("youtube down" in e for e in out["errors"])
    assert out["api"] == {"skipped": "not_set_up"}


def test_card_shows_best_known_save_date(conn, yt):
    w = add(conn, "w1")  # Watch Later only: no save date
    conn.execute("UPDATE items SET added_known = 0 WHERE id = ?", (w,))
    assert library.card(conn, db.get_item(conn, w))["saved_at"] is None
    playlists.refresh_list(conn, S)
    playlists.set_enabled(conn, "PLa", True)
    playlists.sync_enabled(conn, S)
    conn.execute(
        "UPDATE playlist_items SET added_at = '2026-10-30T12:00:00Z' WHERE item_id = 'yt:v1'"
    )
    c = library.card(conn, db.get_item(conn, "yt:v1"))
    assert (c["saved_at"], c["saved_where"]) == ("2026-10-30T12:00:00Z", "Biz ideas")
    library.upsert_item(conn, "b1", source="safari", added_at="2025-01-02T00:00:00+00:00")
    c = library.card(conn, db.get_item(conn, "yt:b1"))
    assert (c["saved_at"], c["saved_where"]) == ("2025-01-02T00:00:00+00:00", "Safari bookmarks")


def test_deck_sort_by_posted_and_saved_with_start_date(conn, yt):
    # posted: a=2020, b=2022, c=2024; saved (playlist dates): only a and c known
    for vid, ts in (("a", 1577880000), ("b", 1641038400), ("c", 1704110400)):
        add(conn, vid)
        conn.execute(
            "UPDATE items SET posted_ts = ?, added_known = 0 WHERE id = ?", (ts, f"yt:{vid}")
        )
    playlists.refresh_list(conn, S)
    conn.execute(
        "INSERT INTO playlist_items (playlist_id, item_id, position, added_at, first_seen)"
        " VALUES ('PLa', 'yt:a', 1, '2026-10-01T00:00:00Z', 't'), ('PLa', 'yt:c', 2, '2025-01-01T00:00:00Z', 't')"
    )
    prep_all(conn)

    def ids(**kw):
        return [c["id"][3:] for c in library.deck(conn, "main", 10, [], "all", **kw)]

    assert ids(sort="posted", direction="desc") == ["c", "b", "a"]
    assert ids(sort="posted", direction="asc") == ["a", "b", "c"]
    assert ids(sort="posted", direction="asc", start="2021-06-01") == [
        "b",
        "c",
    ]  # forward from date
    assert ids(sort="posted", direction="desc", start="2022-01-01") == [
        "b",
        "a",
    ]  # backward, day inclusive
    assert ids(sort="saved", direction="desc") == ["a", "c", "b"]  # unknown save dates last
    assert ids(sort="saved", direction="asc", start="2025-06-01") == ["a"]


def test_deck_sort_api_validation(client, conn):
    assert (
        client.get(
            "/api/deck", params={"sort": "posted", "dir": "asc", "start": "2024-01-31"}
        ).status_code
        == 200
    )
    assert client.get("/api/deck", params={"sort": "bogus"}).status_code == 422
    assert client.get("/api/deck", params={"start": "31/01/2024"}).status_code == 422
