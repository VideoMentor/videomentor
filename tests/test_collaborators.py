"""Two-channel videos: collaborators beside the owner."""

import json

from conftest import add
from videomentor import db, library, sync
from videomentor.config import Settings
from videomentor.sources import youtube

OWNER = "UCHOSTxxxxxxxxxxxxxxxxxx"
GUEST = "UCGUESTxxxxxxxxxxxxxxxxx"

# A trimmed watch page: the owner's id appears near the guest's name first in some layouts.
PAGE = (
    '{"title":"Guest Channel","navigationEndpoint":{"browseEndpoint":{"browseId":"'
    + OWNER
    + '"}}} filler {"text":"Guest Channel","browseEndpoint":{"browseId":"'
    + GUEST
    + '"}}'
)

META = {
    "title": "Ep 410",
    "channel": "Host Channel",
    "channel_id": OWNER,
    "duration_s": 3600,
    "description": "",
    "tags": [],
    "yt_categories": [],
    "upload_date": "20261104",
    "timestamp": 1793000000,
    "channel_handle": "@hostchannel",
    "channel_followers": 5000000,
    "view_count": 1,
    "chapters": [],
    "collaborators": [{"name": "Guest Channel", "channel_id": GUEST}],
}


def test_ids_come_from_the_page_skipping_the_owner():
    assert youtube.collaborator_ids_from_page(PAGE, ["Guest Channel"], OWNER) == {
        "Guest Channel": GUEST
    }
    assert youtube.collaborator_ids_from_page("nothing here", ["Guest Channel"], OWNER) == {}


def test_collaborators_are_creators_besides_the_owner(monkeypatch):
    monkeypatch.setattr(youtube, "_watch_page", lambda vid: "")
    info = {"channel": "Host Channel", "creators": ["Host Channel", "Guest Channel"]}
    assert youtube.collaborators("v", info) == (
        [{"name": "Guest Channel", "channel_id": None}],
        None,
    )
    assert youtube.collaborators("v", {"channel": "Solo", "creators": ["Solo"]}) == ([], None)
    assert youtube.collaborators("v", {"channel": "Solo"}) == ([], None)


def test_enrich_stores_collaborators_and_the_card_shows_them(conn, monkeypatch):
    add(conn, "v1", channel="Host Channel")
    add(conn, "v2", channel="Guest Channel")
    conn.execute("UPDATE items SET enrich_status = 'pending' WHERE id = 'yt:v1'")
    solo = META | {"channel": "Guest Channel", "channel_id": GUEST, "collaborators": []}
    monkeypatch.setattr(youtube, "fetch_metadata", lambda vid, prof: META if vid == "v1" else solo)
    sync.enrich_pending(conn, Settings(pair_code="X"))
    item = db.get_item(conn, "yt:v1")
    assert item["collaborators"] == [{"name": "Guest Channel", "channel_id": GUEST}]
    assert library.card(conn, item)["collaborators"] == item["collaborators"]
    assert library.card(conn, db.get_item(conn, "yt:v2"))["collaborators"] == []


def test_channel_sheet_includes_videos_a_channel_is_credited_on(conn):
    add(conn, "v1", channel="Host Channel")
    conn.execute(
        "UPDATE items SET channel_id = ?, collaborators = ? WHERE id = 'yt:v1'",
        (OWNER, json.dumps([{"name": "Guest Channel", "channel_id": GUEST}])),
    )
    by_id = library.channel_summary(conn, channel_id=GUEST)
    assert by_id["channel"] == "Guest Channel" and by_id["channel_id"] == GUEST
    assert [c["id"] for c in by_id["items"]] == ["yt:v1"]
    assert by_id["handle"] is None  # the owner's handle isn't borrowed
    by_name = library.channel_summary(conn, name="Guest Channel")
    assert by_name["channel_id"] == GUEST
    owner = library.channel_summary(conn, channel_id=OWNER)
    assert owner["channel"] == "Host Channel" and owner["counts"]["saved"] == 1


def test_accented_names_match(conn):
    add(conn, "v1", channel="Owner")
    conn.execute(
        "UPDATE items SET collaborators = ? WHERE id = 'yt:v1'",
        (json.dumps([{"name": "José Núñez", "channel_id": None}], ensure_ascii=False),),
    )
    assert library.channel_summary(conn, name="José Núñez")["channel"] == "José Núñez"
    page = '{"text":"José Núñez","browseId":"' + GUEST + '"}'
    assert youtube.collaborator_ids_from_page(page, ["José Núñez"], OWNER) == {"José Núñez": GUEST}


def test_owner_spellings_and_repeats_are_dropped(monkeypatch):
    info = {
        "channel": "Host Channel",
        "uploader": "Host Channel",
        "creators": ["host channel ", "Guest Channel", "guest channel"],
    }
    assert youtube.collaborator_names(info) == ["Guest Channel"]


def test_owner_followers_come_from_the_page_label():
    page = '"label":"Sample Host, Verified @samplehost 4.49 million subscribers. Go to channel"'
    assert youtube.followers_from_page(page, "Sample Host") == 4_490_000
    page = '"label":"Guest Two | Their Studio, Verified @Art 185 thousand subscribers."'
    assert youtube.followers_from_page(page, "Guest Two | Their Studio") == 185_000
    assert youtube.followers_from_page('"label":"Small, @s 950 subscribers"', "Small") == 950
    assert youtube.followers_from_page("", "Sample Host") is None
    # anchored at the label: "Two" must not match "Guest Two, ..."
    page = '"label":"Guest Two, Verified @guesttwo 12 thousand subscribers."'
    assert youtube.followers_from_page(page, "Two") is None


def test_unknown_followers_keep_the_stored_count(conn, monkeypatch):
    add(conn, "v1", channel="Host Channel")
    conn.execute(
        "UPDATE items SET channel_followers = 5000000, enrich_version = 1 WHERE id = 'yt:v1'"
    )
    monkeypatch.setattr(
        youtube, "fetch_metadata", lambda vid, prof: META | {"channel_followers": None}
    )
    sync.enrich_pending(conn, Settings(pair_code="X"))
    assert db.get_item(conn, "yt:v1")["channel_followers"] == 5000000
