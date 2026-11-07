import json
import plistlib
from pathlib import Path

import pytest

from videomentor.analyze import format_transcript
from videomentor.sources import browser, youtube


@pytest.mark.parametrize(
    "url,vid",
    [
        ("https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=10s", "dQw4w9WgXcQ"),
        ("https://youtu.be/dQw4w9WgXcQ?si=abc", "dQw4w9WgXcQ"),
        ("https://m.youtube.com/shorts/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
        ("https://www.youtube.com/live/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
        ("https://music.youtube.com/watch?v=dQw4w9WgXcQ", "dQw4w9WgXcQ"),
        ("https://www.youtube.com/playlist?list=WL", None),
        ("https://www.youtube.com/@channel", None),
        ("https://example.com/watch?v=dQw4w9WgXcQ", None),
        ("not a url", None),
    ],
)
def test_video_id_from_url(url, vid):
    assert youtube.video_id_from_url(url) == vid


def test_scan_chrome_finds_youtube_links_with_folders_and_dates(tmp_path):
    profile = tmp_path / "Default"
    profile.mkdir()
    data = {
        "roots": {
            "bookmark_bar": {
                "type": "folder",
                "name": "Bar",
                "children": [
                    {
                        "type": "folder",
                        "name": "Learn",
                        "children": [
                            {
                                "type": "url",
                                "name": "Talk",
                                "date_added": "13400000000000000",
                                "url": "https://youtu.be/dQw4w9WgXcQ",
                            },
                        ],
                    },
                    {"type": "url", "name": "Other", "url": "https://example.com"},
                ],
            },
            "sync_transaction_version": "1",
        }
    }
    (profile / "Bookmarks").write_text(json.dumps(data))
    hits = list(browser.scan_chrome("Default", root=tmp_path))
    assert len(hits) == 1
    hit = hits[0]
    assert (hit.video_id, hit.title, hit.folder, hit.source) == (
        "dQw4w9WgXcQ",
        "Talk",
        "/Bar/Learn",
        "chrome:Default",
    )
    assert hit.added_at.startswith("2025-")
    assert browser.chrome_profiles(tmp_path) == ["Default"]


def test_scan_safari(tmp_path):
    path = tmp_path / "Bookmarks.plist"
    data = {
        "Children": [
            {
                "Title": "Favorites",
                "Children": [
                    {
                        "WebBookmarkType": "WebBookmarkTypeLeaf",
                        "URLString": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                        "URIDictionary": {"title": "Song"},
                    },
                ],
            }
        ]
    }
    path.write_bytes(plistlib.dumps(data))
    hits = list(browser.scan_safari(path))
    assert [(h.video_id, h.title, h.folder) for h in hits] == [
        ("dQw4w9WgXcQ", "Song", "/Favorites")
    ]
    assert list(browser.scan_safari(tmp_path / "missing.plist")) == []


def test_parse_json3_and_format_transcript():
    data = {
        "events": [
            {"tStartMs": 0, "segs": [{"utf8": "hello "}, {"utf8": "there"}]},
            {"tStartMs": 5000},
            {"tStartMs": 12000, "segs": [{"utf8": "\n"}]},
            {"tStartMs": 31000, "segs": [{"utf8": "next part"}]},
        ]
    }
    lines = youtube.parse_json3(data)
    assert lines == [(0, "hello there"), (31, "next part")]
    assert format_transcript(lines) == "[0:00 = 0s] hello there\n[0:31 = 31s] next part"


def test_cookie_opts_fall_back_to_saved_file(tmp_path, monkeypatch, vm_home):
    monkeypatch.setattr(youtube, "CHROME_ROOT", tmp_path / "nochrome")
    assert "cookiefile" not in youtube._base_opts("Profile 1")
    youtube.cookie_file().parent.mkdir(parents=True)
    youtube.cookie_file().write_text("# Netscape HTTP Cookie File\n")
    assert youtube._base_opts("Profile 1")["cookiefile"] == str(youtube.cookie_file())
    (tmp_path / "nochrome" / "Profile 1").mkdir(parents=True)
    (tmp_path / "nochrome" / "Profile 1" / "Cookies").write_bytes(b"")
    assert youtube._base_opts("Profile 1")["cookiesfrombrowser"][1] == "Profile 1"


def test_blocked_browser_data_is_skipped_not_fatal(conn, monkeypatch):
    from videomentor import sync
    from videomentor.config import Settings

    def blocked(root=None):
        raise browser.BrowserDataBlocked("nope")

    monkeypatch.setattr(youtube, "chrome_readable", lambda p: False)
    monkeypatch.setattr(youtube, "fetch_watch_later", lambda p: [])
    monkeypatch.setattr(browser, "chrome_profiles", blocked)
    summary = sync.run_sync(conn, Settings(pair_code="X"))
    assert "skipped" in summary["bookmarks"]
    assert sync.last_sync(conn)["finished_at"]


def test_each_fetch_gets_a_private_cookie_copy(tmp_path, monkeypatch, vm_home):
    shared = youtube.cookie_file()
    shared.parent.mkdir(parents=True, exist_ok=True)
    shared.write_text("# Netscape HTTP Cookie File\n")
    seen = []

    class FakeYDL:
        def __init__(self, opts):
            seen.append(opts["cookiefile"])

        def __enter__(self):
            return self

        def __exit__(self, *a):
            # yt-dlp rewrites its cookie file on close; it must not be the shared one
            Path(seen[-1]).write_text("half-writ")

    monkeypatch.setattr(youtube.yt_dlp, "YoutubeDL", FakeYDL)
    with youtube._ydl({"cookiefile": str(shared)}):
        pass
    assert seen[0] != str(shared)
    assert shared.read_text() == "# Netscape HTTP Cookie File\n"


def test_blank_playlist_entries_count_as_unavailable():
    """YouTube lists deleted or private videos in Liked videos with a blank title."""
    info = {
        "entries": [
            {"id": "a", "title": "Real"},
            {"id": "b", "title": ""},
            {"id": "c", "title": None},
        ]
    }
    got = {e.video_id: e.available for e in youtube._entries(info)}
    assert got == {"a": True, "b": False, "c": False}


def test_enrich_with_empty_metadata_archives_the_video(conn, monkeypatch):
    from conftest import add
    from videomentor import db, sync
    from videomentor.config import Settings

    a = add(conn, "gone")
    conn.execute("UPDATE items SET enrich_status = 'pending', title = NULL WHERE id = ?", (a,))
    blank = {
        "title": "",
        "channel": None,
        "channel_id": None,
        "duration_s": None,
        "description": "",
        "tags": [],
        "yt_categories": [],
        "upload_date": None,
        "chapters": [],
    }
    monkeypatch.setattr(youtube, "fetch_metadata", lambda vid, prof: blank)
    sync.enrich_pending(conn, Settings(pair_code="X"))
    item = db.get_item(conn, a)
    assert item["available"] == 0 and item["status"] == "archived"
