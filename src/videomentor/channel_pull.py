"""Channel pulls: bring in a channel's videos that you haven't saved.

Newest N, oldest N (from the channel's first video forward), or a date range, read
from the channel's uploads list with the read-only Data API. Without a current
sign-in, only newest N works (through yt-dlp). Pulled videos are their own source
(`channel:<id>`), kept out of "All saves" so saves and exploration stay apart.
"""

from __future__ import annotations

import heapq
import re
import sqlite3
import threading
from datetime import date, datetime

from . import db, library, youtube_api
from .sources import youtube

MODES = ("newest", "oldest", "range")
MAX_PULL = 200
CHANNEL_ID = re.compile(r"^UC[A-Za-z0-9_-]{22}$")
_busy = threading.Lock()  # one pull at a time: an oldest pull can read 200 pages
# Pages read per pull, across all lists: 10,000 videos, 1 quota unit a page, so 200 at most.
MAX_PAGES = 200


class TooBig(ValueError):
    """The channel has more videos than one pull can read, so "oldest" can't reach the start."""


class NeedsSignIn(Exception):
    """Oldest-first and date ranges need the YouTube Data API sign-in."""


class Busy(Exception):
    """Another channel pull is still running."""


def _check(
    channel_id: str, mode: str, count: int | None, start: str | None, end: str | None
) -> int:
    if not CHANNEL_ID.match(channel_id or ""):
        raise ValueError("not a YouTube channel id (UC followed by 22 characters)")
    if mode not in MODES:
        raise ValueError(f"unknown mode {mode!r}")
    if mode == "range":
        try:
            first, last = date.fromisoformat(start or ""), date.fromisoformat(end or "")
        except ValueError:
            raise ValueError("a date range needs start and end as YYYY-MM-DD") from None
        if len(start) != 10 or len(end) != 10:
            raise ValueError("a date range needs start and end as YYYY-MM-DD")
        if first > last:
            raise ValueError("start must be on or before end")
        return MAX_PULL
    return max(1, min(int(count or 10), MAX_PULL))


def _playlist(playlist_id: str, budget: dict):
    """Videos of one playlist as (video_id, title, published_at), in playlist order (newest first).

    Entries without a publish date (private or deleted) are dropped: they can't be dated or
    watched, and an empty date would stall a merge with other lists. `budget` is shared by
    all lists in one pull: {"pages": left, "cut": True once a list was cut short}.
    """
    params = {"part": "snippet,contentDetails", "playlistId": playlist_id, "maxResults": 50}
    first = True
    while True:
        if budget["pages"] <= 0:
            budget["cut"] = True
            return
        budget["pages"] -= 1
        try:
            page = youtube_api.get("playlistItems", params)
        except youtube_api.ApiError as e:
            if first and "HTTP 404" in str(e):  # a channel with no lives (or no long videos)
                return
            raise
        first = False
        for it in page.get("items", []):
            cd = it.get("contentDetails", {})
            if cd.get("videoId") and cd.get("videoPublishedAt"):
                yield (
                    cd["videoId"],
                    it.get("snippet", {}).get("title"),
                    cd["videoPublishedAt"],
                )
        token = page.get("nextPageToken")
        if not token:
            return
        params = params | {"pageToken": token}


def _lists(include_shorts: bool, include_lives: bool) -> list[str]:
    """Playlist prefixes to read. UU is every upload; YouTube also keeps hidden lists of
    regular videos (UULF), Shorts (UUSH) and live streams (UULV) for each channel."""
    if include_shorts and include_lives:
        return ["UU"]
    return ["UULF"] + (["UUSH"] if include_shorts else []) + (["UULV"] if include_lives else [])


def _uploads(channel_id: str, include_shorts: bool, include_lives: bool, budget: dict):
    """(channel title, iterator of (video_id, title, published_at), newest first), with the
    chosen lists merged by date. Regular videos are always included."""
    body = youtube_api.get("channels", {"part": "snippet", "id": channel_id})
    items = body.get("items") or []
    if not items:
        raise ValueError(f"YouTube has no channel {channel_id}")
    title = items[0]["snippet"]["title"]
    lists = [
        _playlist(prefix + channel_id[2:], budget)
        for prefix in _lists(include_shorts, include_lives)
    ]
    if len(lists) == 1:
        return title, lists[0]
    return title, heapq.merge(*lists, key=lambda v: v[2], reverse=True)


def _local_day(published: str | None) -> str | None:
    """YYYY-MM-DD in local time for a UTC timestamp, so an evening post lands on its own day."""
    if not published:
        return None  # private or deleted entries carry no date
    try:
        return (
            datetime.fromisoformat(published.replace("Z", "+00:00")).astimezone().date().isoformat()
        )
    except ValueError:
        return published[:10]


def _select(
    videos, mode: str, limit: int, start: str | None, end: str | None, known: set[str]
) -> list[tuple]:
    """Pick from videos (newest first). Newest and oldest skip videos already in the library,
    so each pull brings the next N you don't have. A range returns everything in it."""
    if mode == "newest":
        picked = []
        for v in videos:
            if v[0] not in known:
                picked.append(v)
                if len(picked) >= limit:
                    break
        return picked
    if mode == "oldest":
        return [v for v in videos if v[0] not in known][-limit:]
    picked, older = [], 0
    for v in videos:  # range: newest first; stop after a page's worth older than start in a row
        day = _local_day(v[2])
        if not day:
            continue  # private or deleted entries carry no date
        if day < start:
            older += 1
            if older >= 50:  # tolerate a few out of order (premieres, re-dated uploads)
                break
            continue
        older = 0
        if day <= end:
            picked.append(v)
    return picked[:limit]


def pull(
    conn: sqlite3.Connection,
    channel_id: str,
    mode: str,
    count: int | None = None,
    start: str | None = None,
    end: str | None = None,
    chrome_profile: str = "Default",
    include_shorts: bool = False,
    include_lives: bool = False,
) -> dict:
    """Pull up to MAX_PULL uploads from a channel into the library.

    Newest and oldest bring the next N videos not already in the library; a date range
    brings everything in it. Shorts and live streams are skipped unless asked for.
    Returns {channel, channel_id, seen, added, via}: `seen` videos matched, `added` were
    new to the library, `via` is "api" or "yt-dlp". Videos already there keep their status
    and gain the channel source, so nothing is duplicated.
    """
    limit = _check(channel_id, mode, count, start, end)
    if mode != "range":
        start = end = None
    if not _busy.acquire(blocking=False):
        raise Busy("another channel pull is still running; try again in a minute")
    try:
        return _pull(
            conn, channel_id, mode, limit, start, end, chrome_profile, include_shorts, include_lives
        )
    finally:
        _busy.release()


def _pull(
    conn: sqlite3.Connection,
    channel_id: str,
    mode: str,
    limit: int,
    start: str | None,
    end: str | None,
    chrome_profile: str,
    include_shorts: bool,
    include_lives: bool,
) -> dict:
    known = {r[0] for r in conn.execute("SELECT video_id FROM items")}
    if youtube_api.state()["state"] == "ok":
        budget = {"pages": MAX_PAGES, "cut": False}
        title, videos = _uploads(channel_id, include_shorts, include_lives, budget)
        found = _select(videos, mode, limit, start, end, known)
        if mode == "oldest" and budget["cut"]:
            raise TooBig(
                "This channel has more than 10,000 videos, too many to find its oldest. Use Dates instead."
            )
        via = "api"
    else:
        if mode != "newest":
            raise NeedsSignIn(
                "Oldest videos and date ranges need the YouTube sign-in (vm youtube-login)."
            )
        lists = _lists(include_shorts, include_lives)
        if len(lists) > 1:  # yt-dlp gives no dates, so lists can't be merged in order
            raise NeedsSignIn(
                "Mixing Shorts or live streams with videos needs the YouTube sign-in (vm youtube-login)."
            )
        prefix = lists[0]
        try:
            details, entries = youtube.fetch_playlist(prefix + channel_id[2:], chrome_profile)
        except Exception as e:  # e.g. a Shorts-only channel has no regular-videos list
            raise NeedsSignIn(
                "Couldn't read this channel without the YouTube sign-in (vm youtube-login)."
            ) from e
        title = details.get("owner") or details.get("title") or channel_id
        fresh = [(e.video_id, e.title, "") for e in entries if e.available]
        found = _select(fresh, "newest", limit, None, None, known)
        via = "yt-dlp"

    added = 0
    for video_id, video_title, published in found:
        added += library.upsert_item(
            conn,
            video_id,
            source=f"channel:{channel_id}",
            source_ref=title,
            title=video_title,
            channel=title,
            channel_id=channel_id,
        )
        if published:
            ymd = published[:10].replace("-", "")
            conn.execute(
                "UPDATE items SET upload_date = COALESCE(upload_date, ?) WHERE id = ?",
                (ymd, f"yt:{video_id}"),
            )
    conn.execute(
        "INSERT INTO channel_pulls (channel_id, channel, mode, count, start, end, seen, added, via, at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            channel_id,
            title,
            mode,
            None if mode == "range" else limit,
            start,
            end,
            len(found),
            added,
            via,
            db.now(),
        ),
    )
    conn.commit()
    return {
        "channel": title,
        "channel_id": channel_id,
        "seen": len(found),
        "added": added,
        "via": via,
    }


def pulled_channels(conn: sqlite3.Connection) -> list[dict]:
    """Channels pulled from, with counts.

    `videos` = all pulled; `inbox` = not yet triaged, including those still preparing;
    `preparing` = inbox videos not yet tagged and scored (prep_status not done or failed).
    """
    rows = conn.execute(
        "SELECT p.channel_id, p.channel, MAX(p.at) AS last_pull,"
        " (SELECT COUNT(*) FROM item_sources s WHERE s.source = 'channel:' || p.channel_id) AS videos,"
        " (SELECT COUNT(*) FROM item_sources s JOIN items i ON i.id = s.item_id"
        "   WHERE s.source = 'channel:' || p.channel_id AND i.status = 'inbox' AND i.available = 1) AS inbox"
        " , (SELECT COUNT(*) FROM item_sources s JOIN items i ON i.id = s.item_id"
        "   WHERE s.source = 'channel:' || p.channel_id AND i.status = 'inbox' AND i.available = 1"
        "   AND i.prep_status NOT IN ('done','failed')) AS preparing"
        " FROM channel_pulls p GROUP BY p.channel_id ORDER BY last_pull DESC"
    )
    return [dict(r) for r in rows]
