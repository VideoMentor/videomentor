"""YouTube video links saved as Chrome or Safari bookmarks.

Only YouTube video URLs are taken; every other bookmark is ignored.
"""

from __future__ import annotations

import json
import plistlib
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .youtube import video_id_from_url

CHROME_ROOT = Path.home() / "Library/Application Support/Google/Chrome"
SAFARI_BOOKMARKS = Path.home() / "Library/Safari/Bookmarks.plist"

# Chrome stores times as microseconds since 1601-01-01.
_WEBKIT_EPOCH = datetime(1601, 1, 1, tzinfo=UTC)


@dataclass
class BookmarkHit:
    video_id: str
    url: str
    title: str
    folder: str
    source: str
    added_at: str | None


def _webkit_time(value: str | None) -> str | None:
    try:
        micros = int(value or 0)
    except ValueError:
        return None
    if micros <= 0:
        return None
    return (_WEBKIT_EPOCH + timedelta(microseconds=micros)).isoformat(timespec="seconds")


class BrowserDataBlocked(Exception):
    """macOS keeps the login service out of browser data; run `vm sync` in Terminal."""


def chrome_profiles(root: Path = CHROME_ROOT) -> list[str]:
    try:
        return sorted(p.name for p in root.iterdir() if (p / "Bookmarks").is_file())
    except FileNotFoundError:
        return []
    except PermissionError as e:
        raise BrowserDataBlocked(str(e)) from e


def scan_chrome(profile: str, root: Path = CHROME_ROOT) -> Iterator[BookmarkHit]:
    path = root / profile / "Bookmarks"
    try:
        data = json.loads(path.read_text())
    except FileNotFoundError:
        return
    except PermissionError as e:
        raise BrowserDataBlocked(str(e)) from e

    def walk(node: dict, folder: str) -> Iterator[BookmarkHit]:
        if node.get("type") == "url":
            vid = video_id_from_url(node.get("url", ""))
            if vid:
                yield BookmarkHit(
                    video_id=vid,
                    url=node["url"],
                    title=node.get("name", ""),
                    folder=folder,
                    source=f"chrome:{profile}",
                    added_at=_webkit_time(node.get("date_added")),
                )
        for child in node.get("children", []):
            name = node.get("name", "") if node.get("type") == "folder" else ""
            yield from walk(child, f"{folder}/{name}" if name else folder)

    for root_node in data.get("roots", {}).values():
        if isinstance(root_node, dict):
            yield from walk(root_node, "")


def scan_safari(path: Path = SAFARI_BOOKMARKS) -> Iterator[BookmarkHit]:
    try:
        data = plistlib.loads(path.read_bytes())
    except (OSError, plistlib.InvalidFileException):
        # Missing file, or no Full Disk Access for the process reading it.
        return

    def walk(node: dict, folder: str) -> Iterator[BookmarkHit]:
        if node.get("WebBookmarkType") == "WebBookmarkTypeLeaf":
            url = node.get("URLString", "")
            vid = video_id_from_url(url)
            if vid:
                yield BookmarkHit(
                    video_id=vid,
                    url=url,
                    title=(node.get("URIDictionary") or {}).get("title", ""),
                    folder=folder,
                    source="safari",
                    added_at=None,
                )
        name = node.get("Title", "")
        for child in node.get("Children") or []:
            yield from walk(child, f"{folder}/{name}" if name else folder)

    yield from walk(data, "")
