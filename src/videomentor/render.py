"""Rendered training video: one MP4 from a training module.

Narrated title cards between clips from different videos, optional web screens, and a
credits card. Cards and screens are headless-Chrome screenshots, narration is macOS
`say`, clips are just the needed sections downloaded with yt-dlp, and ffmpeg joins it
all. Downloading clips is for personal use only: rendered videos are not for sharing.
"""

from __future__ import annotations

import fcntl
import html
import json
import os
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

import yt_dlp
import yt_dlp.utils

from .config import library_home
from .sources import youtube

W, H, FPS = 1280, 720, 30
VOICE = "Samantha"
CARD_PAD = 0.8  # seconds a card stays up after its narration
SILENT_CARD = 4.0  # seconds for a card when narration is off or fails
CLIP_DAYS = 30  # clips not reused for this long are deleted after a render


class RenderError(Exception):
    pass


class Busy(RenderError):
    """Another video is rendering."""


@dataclass
class Segment:
    kind: str  # "card" | "clip" | "screen"
    title: str = ""
    lines: list[str] = field(default_factory=list)
    style: str = "cue"  # card look: intro, lesson, cue, exercise, done, credits
    video_id: str = ""
    start: int = 0
    end: int = 0
    url: str = ""

    @property
    def narration(self) -> str:
        if self.kind == "clip" or self.style == "credits":
            return ""
        if self.kind == "screen":
            return self.lines[0] if self.lines else f"Have a look at {urlparse(self.url).netloc}."
        return ". ".join([self.title, *self.lines]).replace("..", ".")


def video_dir() -> Path:
    return library_home() / "training" / "videos"


def video_path(module_id: int) -> Path:
    return video_dir() / f"module-{module_id}.mp4"


def _status_path(module_id: int) -> Path:
    return video_dir() / f"module-{module_id}.json"


def status(module_id: int) -> dict:
    """{state: none|rendering|ready|failed, done, total, error, finished_at}."""
    p = _status_path(module_id)
    try:
        s = json.loads(p.read_text())
    except (OSError, ValueError):
        s = {"state": "none"}
    if s.get("state") == "ready" and not video_path(module_id).exists():
        s = {"state": "none"}
    # "rendering" with no render running (server restarted mid-render): say so. The grace
    # period covers the moment between mark_queued and the render taking the lock.
    try:
        age = time.time() - p.stat().st_mtime
    except OSError:
        age = 0
    if s.get("state") == "rendering" and age > 30 and not is_busy():
        s = {"state": "failed", "error": "The render was interrupted. Start it again."}
    return s


class _RenderLock:
    """One render at a time across processes (the server and `vm render`), via flock."""

    def __init__(self) -> None:
        self.fd: int | None = None

    def acquire(self) -> bool:
        video_dir().mkdir(parents=True, exist_ok=True)
        fd = os.open(video_dir() / "render.lock", os.O_RDWR | os.O_CREAT, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            os.close(fd)
            return False
        self.fd = fd
        return True

    def release(self) -> None:
        if self.fd is not None:
            fcntl.flock(self.fd, fcntl.LOCK_UN)
            os.close(self.fd)
            self.fd = None


def is_busy() -> bool:
    lock = _RenderLock()
    if lock.acquire():
        lock.release()
        return False
    return True


def check_tools() -> None:
    """Raise RenderError naming what's missing, before a render is queued."""
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        raise RenderError("ffmpeg is needed on the Mac (brew install ffmpeg)")
    _chrome()


def clear_queued(module_id: int) -> None:
    """Undo mark_queued, unless a render has already written real progress."""
    p = _status_path(module_id)
    try:
        if json.loads(p.read_text()).get("queued"):
            p.unlink(missing_ok=True)
    except (OSError, ValueError):
        pass


def mark_queued(module_id: int) -> None:
    """Show "rendering" right away, before the render thread takes the lock."""
    _set_status(module_id, state="rendering", done=0, total=0, queued=True)


def _set_status(module_id: int, **s) -> None:
    video_dir().mkdir(parents=True, exist_ok=True)
    _status_path(module_id).write_text(json.dumps(s))


def _video_id(v: str) -> str:
    return v.removeprefix("yt:")


def parse_screens(specs: list[str]) -> dict[int, list[tuple[str, str]]]:
    """ "2=https://example.com" or "2=https://example.com|What to notice" -> {lesson index: [(url, line)]}."""
    out: dict[int, list[tuple[str, str]]] = {}
    for spec in specs:
        num, _, rest = spec.partition("=")
        url, _, line = rest.partition("|")
        if not num.strip().isdigit() or urlparse(url.strip()).scheme not in ("http", "https"):
            raise ValueError(f"screen must look like 2=https://example.com, got {spec!r}")
        out.setdefault(int(num) - 1, []).append((url.strip(), line.strip()))
    return out


def plan(
    module: dict,
    screens: dict[int, list[tuple[str, str]]] | None = None,
    max_clips: int | None = None,
) -> list[Segment]:
    """Intro, then per lesson: its card, any web screens, a cue card and the clip for each
    clip, its exercise; then a finish card and credits. Mirrors the in-app lesson player."""
    screens = screens or {}
    lessons = module["lessons"]
    all_clips = [c for lesson in lessons for c in lesson["clips"]][: max_clips or None]
    keep = {id(c) for c in all_clips}
    videos = {c["video"] for c in all_clips}
    watch = sum(max(0, c["end"] - c["start"]) for c in all_clips)
    segs = [
        Segment(
            "card",
            module["title"],
            [
                module.get("outcome") or "",
                f"{len(all_clips)} clips from {len(videos)} videos, about {max(1, round(watch / 60))} minutes of video.",
            ],
            style="intro",
        )
    ]
    sources: dict[str, dict] = {}
    for i, lesson in enumerate(lessons):
        clips = [c for c in lesson["clips"] if id(c) in keep]
        if not clips and not screens.get(i):
            continue
        segs.append(
            Segment(
                "card",
                f"Lesson {i + 1}: {lesson['title']}",
                [lesson.get("goal") or ""],
                style="lesson",
            )
        )
        for url, line in screens.get(i, []):
            segs.append(Segment("screen", lines=[line] if line else [], url=url))
        for c in clips:
            segs.append(
                Segment(
                    "card",
                    c.get("title") or "Next clip",
                    [c.get("why") or "", f"Watch for: {c.get('watch_for') or ''}"],
                    style="cue",
                )
            )
            segs.append(
                Segment(
                    "clip",
                    c.get("title") or "",
                    video_id=_video_id(c["video"]),
                    start=int(c["start"]),
                    end=int(c["end"]),
                )
            )
            sources.setdefault(c["video"], c)
        if lesson.get("exercise"):
            segs.append(Segment("card", "Try it", [lesson["exercise"]], style="exercise"))
    segs.append(
        Segment(
            "card", "Lesson complete", ["Check yourself with the quiz in the app."], style="done"
        )
    )
    segs.append(
        Segment(
            "card",
            "Sources",
            [
                f"{c.get('title') or _video_id(v)} · {c.get('channel') or ''} · youtu.be/{_video_id(v)}"
                for v, c in sources.items()
            ]
            + ["Clips belong to their creators. Personal use only: not for sharing."],
            style="credits",
        )
    )
    return segs


CARD_CSS = """
* { margin: 0; box-sizing: border-box; }
html, body { width: 1280px; height: 720px; }
body { background: #0f172a; color: #f8fafc; font-family: "Avenir Next", -apple-system, Helvetica, sans-serif;
  display: flex; flex-direction: column; justify-content: center; padding: 72px 96px; gap: 22px; }
.kicker { color: #fbbf24; font-size: 22px; font-weight: 600; letter-spacing: 0.12em; text-transform: uppercase; }
h1 { font-size: 54px; line-height: 1.12; font-weight: 700; }
p { font-size: 28px; line-height: 1.4; color: #cbd5e1; }
p.lead { font-size: 32px; color: #f8fafc; }
.lesson { background: #1e3a8a; } .exercise { background: #14532d; } .done { background: #4c1d95; }
.credits h1 { font-size: 40px; } .credits p { font-size: 20px; line-height: 1.35; }
.foot { position: absolute; bottom: 28px; left: 96px; font-size: 16px; color: #64748b; }
"""

KICKER = {
    "intro": "Training",
    "lesson": "Lesson",
    "cue": "Next clip",
    "exercise": "Try it",
    "done": "Done",
    "credits": "Credits",
}


def card_html(seg: Segment) -> str:
    e = html.escape
    lines = "".join(
        f'<p class="{"lead" if k == 0 and seg.style != "credits" else ""}">{e(t)}</p>'
        for k, t in enumerate(seg.lines)
        if t
    )
    foot = (
        '<div class="foot">Personal use only · clips belong to their creators</div>'
        if seg.style == "intro"
        else ""
    )
    return (
        f'<!doctype html><html><head><meta charset="utf-8"><style>{CARD_CSS}</style></head>'
        f'<body class="{e(seg.style)}"><div class="kicker">{e(KICKER.get(seg.style, ""))}</div>'
        f"<h1>{e(seg.title)}</h1>{lines}{foot}</body></html>"
    )


# --- tools ------------------------------------------------------------------------


def _chrome() -> str:
    mac = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    found = mac if Path(mac).exists() else shutil.which("google-chrome") or shutil.which("chromium")
    if not found:
        raise RenderError("Google Chrome is needed for cards and screens")
    return found


def _run(cmd: list[str], timeout: int = 300) -> None:
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if proc.returncode != 0:
        raise RenderError(f"{Path(cmd[0]).name} failed: {(proc.stderr or proc.stdout)[-400:]}")


def screenshot(target: str, out: Path, profile_dir: Path) -> None:
    _run(
        [
            _chrome(),
            "--headless=new",
            "--disable-gpu",
            "--hide-scrollbars",
            "--no-first-run",
            f"--user-data-dir={profile_dir}",  # a throwaway profile, never the user's own
            f"--window-size={W},{H}",
            "--virtual-time-budget=6000",
            f"--screenshot={out}",
            target,
        ],
        timeout=90,
    )
    if not out.exists():
        raise RenderError(f"no screenshot of {target}")


def speak(text: str, out: Path, voice: str) -> bool:
    if not text.strip() or not shutil.which("say"):
        return False
    script = out.with_suffix(".txt")
    script.write_text(text)
    try:
        _run(["say", "-v", voice, "-o", str(out), "-f", str(script)], timeout=120)
    except RenderError:
        return False
    return out.exists()


def duration(path: Path) -> float:
    proc = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        capture_output=True,
        text=True,
    )
    try:
        return float(proc.stdout.strip())
    except ValueError:
        return 0.0


ENCODE = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "22", "-pix_fmt", "yuv420p", "-r", str(FPS),
          "-c:a", "aac", "-ar", "48000", "-ac", "2", "-movflags", "+faststart"]  # fmt: skip
FIT = f"scale={W}:{H}:force_original_aspect_ratio=decrease,pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1"


def still(png: Path, audio: Path | None, out: Path) -> None:
    """A still image for the length of its narration (plus a beat), or SILENT_CARD seconds."""
    secs = (duration(audio) + CARD_PAD) if audio else SILENT_CARD
    inputs = ["-loop", "1", "-i", str(png)]
    inputs += ["-i", str(audio)] if audio else ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo"]
    _run(
        ["ffmpeg", "-y", *inputs, "-t", f"{secs:.2f}", "-vf", FIT, "-af", "apad", *ENCODE, str(out)]
    )


def fetch_clip(seg: Segment, cache: Path, chrome_profile: str) -> Path:
    """Download only the clip's section (720p at most); reuse it on later renders."""
    cache.mkdir(parents=True, exist_ok=True)
    stem = f"{seg.video_id}_{seg.start}_{seg.end}"
    final = cache / f"{stem}.mp4"
    if final.exists():
        os.utime(final)  # recently used: keep it in the cache
        return final
    # Download into a scratch folder and move only a finished, merged file into the cache,
    # so an interrupted download (.part, .ytdl, a lone video stream) is never reused.
    scratch = Path(tempfile.mkdtemp(prefix="clip-", dir=cache))
    opts = youtube._cookie_opts(chrome_profile) | {
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "format": "bv*[height<=720]+ba/b[height<=720]/b",
        "merge_output_format": "mp4",
        "download_ranges": yt_dlp.utils.download_range_func(None, [(seg.start, seg.end)]),
        "force_keyframes_at_cuts": True,
        "outtmpl": str(scratch / "clip.%(ext)s"),
        "js_runtimes": {"node": {}, "deno": {}},
        "socket_timeout": 30,
        "retries": 3,
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([youtube.watch_url(seg.video_id)])
        done = scratch / "clip.mp4"
        if not done.exists():
            raise RenderError(f"clip {seg.video_id} {seg.start}-{seg.end} did not download")
        done.replace(final)
        return final
    except yt_dlp.utils.DownloadError as e:
        raise RenderError(f"clip {seg.video_id} {seg.start}-{seg.end}: {e}") from None
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


def prune_clips(cache: Path, days: int = CLIP_DAYS) -> int:
    """Delete cached clips not used for `days` days; returns how many."""
    cutoff = time.time() - days * 86400
    gone = 0
    for f in cache.glob("*.mp4"):
        if f.stat().st_mtime < cutoff:
            f.unlink(missing_ok=True)
            gone += 1
    return gone


def normalize(src: Path, out: Path) -> None:
    """Same size, frame rate and sound format as the cards, so the parts join cleanly."""
    has_audio = (
        "audio"
        in subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "stream=codec_type",
                "-of",
                "csv=p=0",
                str(src),
            ],
            capture_output=True,
            text=True,
        ).stdout
    )
    inputs = ["-i", str(src)] + (
        [] if has_audio else ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo", "-shortest"]
    )
    _run(["ffmpeg", "-y", *inputs, "-vf", FIT, *ENCODE, str(out)], timeout=900)


def concat(parts: list[Path], out: Path, work: Path) -> None:
    listing = work / "parts.txt"
    listing.write_text("".join(f"file '{p.as_posix()}'\n" for p in parts))
    _run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(listing),
            "-c",
            "copy",
            "-movflags",
            "+faststart",
            str(out),
        ],
        timeout=900,
    )


# --- the render -------------------------------------------------------------------


def render(
    module_id: int,
    module: dict,
    *,
    screens: dict[int, list[tuple[str, str]]] | None = None,
    voice: str = VOICE,
    max_clips: int | None = None,
    chrome_profile: str = "Default",
    progress=None,
) -> Path:
    """Render the module to <library>/training/videos/module-<id>.mp4. One render at a time."""
    check_tools()
    lock = _RenderLock()
    if not lock.acquire():
        raise Busy("another training video is rendering")
    total = 0
    try:
        segs = plan(
            module, screens, max_clips
        )  # inside try: a malformed module must not keep the lock
        total = len(segs)
        _set_status(
            module_id,
            state="rendering",
            done=0,
            total=total,
            started_at=datetime.now().astimezone().isoformat(),
        )
        cache = video_dir() / "clips"
        with tempfile.TemporaryDirectory(prefix="vm-render-") as tmp:
            work = Path(tmp)
            profile = work / "chrome"
            parts: list[Path] = []
            for n, seg in enumerate(segs):
                part = work / f"{n:03d}.mp4"
                if seg.kind == "clip":
                    normalize(fetch_clip(seg, cache, chrome_profile), part)
                else:
                    png = work / f"{n:03d}.png"
                    if seg.kind == "card":
                        page = work / f"{n:03d}.html"
                        page.write_text(card_html(seg))
                        screenshot(page.as_uri(), png, profile)
                    else:
                        screenshot(seg.url, png, profile)
                    audio = work / f"{n:03d}.aiff"
                    still(png, audio if speak(seg.narration, audio, voice) else None, part)
                parts.append(part)
                _set_status(module_id, state="rendering", done=n + 1, total=total)
                if progress:
                    progress(n + 1, total, seg)
            out = video_path(module_id)
            tmp_out = out.with_suffix(".part.mp4")
            concat(parts, tmp_out, work)
            tmp_out.replace(out)
        prune_clips(cache)
        _set_status(
            module_id,
            state="ready",
            done=total,
            total=total,
            seconds=round(duration(out)),
            finished_at=datetime.now().astimezone().isoformat(),
        )
        return out
    except Exception as e:
        msg = str(e) if isinstance(e, RenderError) else f"{type(e).__name__}: {e}"
        _set_status(module_id, state="failed", error=msg[-400:], total=total)
        raise
    finally:
        lock.release()
