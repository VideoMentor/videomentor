"""YouTube access through yt-dlp, signed in with the browser's cookies.

Read-only: nothing here changes anything on the YouTube account.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
import urllib.request
from contextlib import contextmanager
from dataclasses import dataclass
from http.cookiejar import MozillaCookieJar
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import yt_dlp
import yt_dlp.cookies

from ..config import library_home

CHROME_ROOT = Path.home() / "Library/Application Support/Google/Chrome"

WATCH_LATER_URL = "https://www.youtube.com/playlist?list=WL"
UNAVAILABLE_TITLES = {"[Private video]", "[Deleted video]", "[Unavailable video]"}

_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")


def video_id_from_url(url: str) -> str | None:
    """Return the 11-character video id for a YouTube video URL, else None."""
    try:
        parsed = urlparse(url.strip())
    except ValueError:
        return None
    host = (parsed.hostname or "").lower().removeprefix("www.").removeprefix("m.")
    candidate = None
    if host == "youtu.be":
        candidate = parsed.path.lstrip("/").split("/")[0]
    elif host in {"youtube.com", "music.youtube.com", "youtube-nocookie.com"}:
        if parsed.path == "/watch":
            candidate = (parse_qs(parsed.query).get("v") or [None])[0]
        else:
            parts = parsed.path.strip("/").split("/")
            if len(parts) >= 2 and parts[0] in {"shorts", "live", "embed", "v"}:
                candidate = parts[1]
    if candidate and _ID.match(candidate):
        return candidate
    return None


def watch_url(video_id: str) -> str:
    return f"https://www.youtube.com/watch?v={video_id}"


def thumbnail_url(video_id: str) -> str:
    return f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"


@dataclass
class PlaylistEntry:
    video_id: str
    title: str | None
    channel: str | None
    channel_id: str | None
    duration_s: int | None
    position: int
    available: bool


def cookie_file() -> Path:
    return library_home() / "secrets" / "youtube-cookies.txt"


def chrome_readable(chrome_profile: str) -> bool:
    """False inside the login service, which macOS keeps out of Chrome's data folder."""
    try:
        with open(CHROME_ROOT / chrome_profile / "Cookies", "rb"):
            return True
    except OSError:
        return False


@contextmanager
def _ydl(opts: dict):
    """A YoutubeDL with a private copy of the saved login file.

    yt-dlp writes the cookie file back when it closes, so parallel fetches sharing
    one file can leave it half-written for the next reader.
    """
    if "cookiefile" not in opts:
        with yt_dlp.YoutubeDL(opts) as ydl:
            yield ydl
        return
    with tempfile.TemporaryDirectory() as tmp:
        private = Path(tmp) / "cookies.txt"
        shutil.copyfile(opts["cookiefile"], private)
        with yt_dlp.YoutubeDL(opts | {"cookiefile": str(private)}) as ydl:
            yield ydl


def export_cookies(chrome_profile: str) -> int:
    """Save the YouTube and Google login cookies for the service to use."""
    jar = yt_dlp.cookies.extract_cookies_from_browser("chrome", chrome_profile)
    path = cookie_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.parent.chmod(0o700)
    # Write a temp file and swap it in, so a reader never sees a half-written file.
    tmp = path.with_suffix(".tmp")
    out = MozillaCookieJar(str(tmp))
    for cookie in jar:
        if cookie.domain.lstrip(".").endswith(("youtube.com", "google.com")):
            out.set_cookie(cookie)
    out.save(ignore_discard=True, ignore_expires=True)
    tmp.chmod(0o600)
    os.replace(tmp, path)
    return len(out)


def _cookie_opts(chrome_profile: str) -> dict:
    if chrome_readable(chrome_profile):
        return {"cookiesfrombrowser": ("chrome", chrome_profile, None, None)}
    if cookie_file().exists():
        return {"cookiefile": str(cookie_file())}
    return {}


def _base_opts(chrome_profile: str) -> dict:
    return _cookie_opts(chrome_profile) | {
        "quiet": True,
        "noprogress": True,
        "no_warnings": True,
        "skip_download": True,
        "ignore_no_formats_error": True,
        # YouTube's player challenges need a JS runtime to unlock captions; Node is
        # installed, Deno (yt-dlp's default) isn't.
        "js_runtimes": {"node": {}, "deno": {}},
    }


def playlist_url(playlist_id: str) -> str:
    return f"https://www.youtube.com/playlist?list={playlist_id}"


def _entries(info: dict) -> list[PlaylistEntry]:
    entries = []
    for pos, e in enumerate(info.get("entries") or [], start=1):
        if not e or not e.get("id"):
            continue
        title = e.get("title")
        duration = e.get("duration")
        entries.append(
            PlaylistEntry(
                video_id=e["id"],
                title=title,
                channel=e.get("channel") or e.get("uploader"),
                channel_id=e.get("channel_id"),
                duration_s=int(duration) if duration else None,
                position=pos,
                # Deleted or private videos come back labeled, or (in Liked videos)
                # with a blank title.
                available=bool(title and title.strip()) and title not in UNAVAILABLE_TITLES,
            )
        )
    return entries


def _playlist_details(info: dict) -> dict:
    return {
        "title": info.get("title"),
        "video_count": info.get("playlist_count"),
        "modified_date": info.get("modified_date"),
        "owner": info.get("uploader") or info.get("channel"),
        "owner_channel_id": info.get("channel_id"),
        "visibility": info.get("availability"),
    }


def fetch_watch_later(chrome_profile: str) -> list[PlaylistEntry]:
    return fetch_playlist(WATCH_LATER_URL.split("=")[-1], chrome_profile)[1]


def fetch_playlist(playlist_id: str, chrome_profile: str) -> tuple[dict, list[PlaylistEntry]]:
    """Every video in a playlist, in its stored order, plus the playlist's details."""
    opts = _base_opts(chrome_profile) | {"extract_flat": "in_playlist"}
    with _ydl(opts) as ydl:
        info = ydl.extract_info(playlist_url(playlist_id), download=False)
    return _playlist_details(info), _entries(info)


def fetch_playlist_feed(chrome_profile: str) -> list[tuple[str, str | None]]:
    """(id, title) of every playlist in the account's library, in YouTube's order."""
    opts = _base_opts(chrome_profile) | {"extract_flat": "in_playlist"}
    with _ydl(opts) as ydl:
        info = ydl.extract_info("https://www.youtube.com/feed/playlists", download=False)
    return [(e["id"], e.get("title")) for e in info.get("entries") or [] if e and e.get("id")]


def fetch_playlist_details(playlist_id: str, chrome_profile: str) -> dict:
    """Count, last updated, owner and visibility, reading only the first page."""
    opts = _base_opts(chrome_profile) | {"extract_flat": "in_playlist", "playlistend": 1}
    with _ydl(opts) as ydl:
        info = ydl.extract_info(playlist_url(playlist_id), download=False)
    return _playlist_details(info)


def fetch_metadata(video_id: str, chrome_profile: str) -> dict:
    """Full metadata for one video. Raises yt_dlp.utils.DownloadError if unavailable."""
    with _ydl(_base_opts(chrome_profile)) as ydl:
        info = ydl.extract_info(watch_url(video_id), download=False, process=False)
    chapters = [
        {"t": int(c.get("start_time") or 0), "label": c.get("title") or ""}
        for c in info.get("chapters") or []
    ]
    duration = info.get("duration")
    meta = {
        "title": info.get("title"),
        "channel": info.get("channel") or info.get("uploader"),
        "channel_id": info.get("channel_id"),
        "duration_s": int(duration) if duration else None,
        "description": info.get("description") or "",
        "tags": info.get("tags") or [],
        "yt_categories": info.get("categories") or [],
        "upload_date": info.get("upload_date"),
        # Exact publish time (Unix seconds); premieres and streams use release_timestamp.
        "timestamp": info.get("timestamp") or info.get("release_timestamp"),
        "channel_handle": info.get("uploader_id"),
        "channel_followers": info.get("channel_follower_count"),
        "view_count": info.get("view_count"),
        "chapters": chapters,
    }
    collabs, owner_followers = collaborators(video_id, info)
    meta["collaborators"] = collabs
    if collabs:  # yt-dlp's count is wrong on collaboration pages; None keeps the stored one
        meta["channel_followers"] = owner_followers
    return meta


def collaborator_names(info: dict) -> list[str]:
    """Creators credited besides the owner (any spelling of the owner, no repeats)."""
    seen = {(info.get(k) or "").strip().casefold() for k in ("channel", "uploader")} - {""}
    names = []
    for n in info.get("creators") or []:
        key = (n or "").strip().casefold()
        if key and key not in seen:
            seen.add(key)
            names.append(n.strip())
    return names


def collaborators(video_id: str, info: dict) -> tuple[list[dict], int | None]:
    """(channels credited besides the owner, the owner's subscriber count from the page).

    YouTube collaborations: yt-dlp lists every creator's name; the Data API
    reports only the owner. Channel ids come from the watch page, best effort: a name without
    an id still shows. On these pages yt-dlp misreads the owner's subscribers ("4.49M" as
    449), so the count is read from the page's own label instead (None if not found).
    """
    names = collaborator_names(info)
    if not names:
        return [], None
    page = _watch_page(video_id)
    ids = collaborator_ids_from_page(page, names, exclude=info.get("channel_id"))
    owner = info.get("channel") or info.get("uploader") or ""
    return [{"name": n, "channel_id": ids.get(n)} for n in names], followers_from_page(page, owner)


def _watch_page(video_id: str) -> str:
    try:
        req = urllib.request.Request(watch_url(video_id), headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15) as r:  # noqa: S310 (fixed youtube.com URL)
            if not r.geturl().startswith("https://www.youtube.com/"):
                return ""  # redirected elsewhere (consent page, another host): skip
            return r.read(4_000_000).decode("utf-8", "ignore")
    except Exception:  # best effort (incl. IncompleteRead)
        return ""


_SCALE = {"thousand": 1_000, "million": 1_000_000, "billion": 1_000_000_000}


def followers_from_page(page: str, channel: str) -> int | None:
    """Subscribers from a label like "Sample Host, Verified @samplehost 4.49 million subscribers"."""
    if not page or not channel:
        return None
    m = re.search(
        r'"label":"'
        + re.escape(channel)
        + r',[^"]{0,120}?([\d.,]+)\s*(thousand|million|billion)?\s+subscribers',
        page,
    )
    if not m:
        return None
    try:
        return round(float(m.group(1).replace(",", "")) * _SCALE.get(m.group(2) or "", 1))
    except ValueError:
        return None


def collaborator_ids_from_page(page: str, names: list[str], exclude: str | None) -> dict[str, str]:
    """The first channel id after each name in the page data, skipping the owner's."""
    out: dict[str, str] = {}
    for name in names:
        needle = json.dumps(name, ensure_ascii=False)  # names appear as JSON strings in the page
        start = 0
        while (at := page.find(needle, start)) != -1 and name not in out:
            for cid in re.findall(r'"browseId":"(UC[\w-]{22})"', page[at : at + 1200]):
                if cid != exclude:
                    out[name] = cid
                    break
            start = at + len(needle)
    return out


def parse_json3(data: dict) -> list[tuple[int, str]]:
    """Turn a json3 caption track into (start_seconds, text) lines."""
    lines = []
    for event in data.get("events") or []:
        segs = event.get("segs")
        if not segs:
            continue
        text = "".join(s.get("utf8", "") for s in segs).replace("\n", " ").strip()
        if text:
            lines.append((int((event.get("tStartMs") or 0) / 1000), text))
    return lines


def fetch_transcript(video_id: str, chrome_profile: str) -> list[tuple[int, str]] | None:
    """English captions (manual preferred, then auto), or None if the video has none."""
    with tempfile.TemporaryDirectory() as tmp:
        opts = _base_opts(chrome_profile) | {
            "writesubtitles": True,
            "writeautomaticsub": True,
            "subtitleslangs": ["en", "en-US", "en-GB", "en-orig"],
            "subtitlesformat": "json3",
            "outtmpl": str(Path(tmp) / "%(id)s.%(ext)s"),
        }
        with _ydl(opts) as ydl:
            ydl.download([watch_url(video_id)])
        tracks = sorted(Path(tmp).glob(f"{video_id}*.json3"))
        if not tracks:
            return None
        # Manual tracks are named like id.en.json3; prefer the shortest language tag.
        best = min(tracks, key=lambda p: len(p.name))
        return parse_json3(json.loads(best.read_text()))
