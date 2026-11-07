"""Rendered training video: plan, cards, screens, status and API."""

import json
import os
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from videomentor import db, render, training
from videomentor.api import create_app
from videomentor.config import Settings


def clip(v, start, end, channel="Chan"):
    return {"video": f"yt:{v}", "start": start, "end": end, "why": f"why {v}", "watch_for": f"watch {v}",
            "title": f"Title <{v}>", "channel": channel}  # fmt: skip


MODULE = {
    "title": "Hard talks",
    "outcome": "Say it kindly.",
    "lessons": [
        {
            "title": "Open",
            "goal": "Start well",
            "clips": [clip("a", 10, 70), clip("b", 0, 120)],
            "exercise": "Practice",
        },
        {"title": "Close", "goal": "End well", "clips": [clip("a", 300, 360)], "exercise": ""},
    ],
    "quiz": [],
}


def kinds(segs):
    return [s.kind if s.kind != "card" else s.style for s in segs]


def test_plan_mirrors_the_lesson_player_and_ends_with_credits():
    segs = render.plan(MODULE)
    assert kinds(segs) == [
        "intro",
        "lesson",
        "cue",
        "clip",
        "cue",
        "clip",
        "exercise",
        "lesson",
        "cue",
        "clip",
        "done",
        "credits",
    ]
    assert segs[3].video_id == "a" and (segs[3].start, segs[3].end) == (10, 70)
    assert segs[0].lines[1] == "3 clips from 2 videos, about 4 minutes of video."
    credits = segs[-1].lines
    assert len(credits) == 3 and credits[0].startswith("Title <a> · Chan · youtu.be/a")
    assert "not for sharing" in credits[-1]


def test_max_clips_trims_and_drops_empty_lessons():
    segs = render.plan(MODULE, max_clips=1)
    assert kinds(segs) == ["intro", "lesson", "cue", "clip", "exercise", "done", "credits"]


def test_screens_follow_their_lesson_card():
    screens = render.parse_screens(
        ["2=https://example.com/docs|Notice the sidebar", "1=https://example.org"]
    )
    assert screens == {
        1: [("https://example.com/docs", "Notice the sidebar")],
        0: [("https://example.org", "")],
    }
    segs = render.plan(MODULE, screens)
    assert kinds(segs)[1:3] == ["lesson", "screen"] and kinds(segs)[8:10] == ["lesson", "screen"]
    assert segs[2].narration == "Have a look at example.org."
    assert segs[9].narration == "Notice the sidebar"
    for bad in ("x=https://a.b", "2=file:///etc/passwd", "2=javascript:alert(1)", "2"):
        with pytest.raises(ValueError):
            render.parse_screens([bad])


def test_cards_escape_text_and_narrate():
    seg = render.plan(MODULE)[2]
    page = render.card_html(seg)
    assert "Title &lt;a&gt;" in page and "<a>" not in page
    assert seg.narration == "Title <a>. why a. Watch for: watch a"
    assert render.plan(MODULE)[-1].narration == ""  # credits are read, not spoken


def test_status_reports_missing_videos_and_interrupted_renders():
    assert render.status(7) == {"state": "none"}
    render._set_status(7, state="ready", done=3, total=3)
    assert render.status(7) == {"state": "none"}  # file gone
    render.video_path(7).write_bytes(b"mp4")
    assert render.status(7)["state"] == "ready"
    render._set_status(8, state="rendering", done=1, total=9)
    assert render.status(8)["state"] == "rendering"  # just started
    old = time.time() - 120
    os.utime(render._status_path(8), (old, old))
    assert render.status(8)["state"] == "failed"


def test_render_endpoints(conn, monkeypatch):
    conn.execute(
        "INSERT INTO training_modules (tag, status, title, module, created_at) VALUES (?, 'ready', ?, ?, ?)",
        ("talks", "Hard talks", json.dumps(MODULE), db.now()),
    )
    conn.commit()
    mid = training.list_modules(conn)[0]["id"]
    started = []

    def fake_render(module_id, module, **kw):
        started.append(module_id)
        render.video_path(module_id).parent.mkdir(parents=True, exist_ok=True)
        render.video_path(module_id).write_bytes(b"\x00" * 2048)
        render._set_status(module_id, state="ready", done=1, total=1)

    monkeypatch.setattr(render, "render", fake_render)
    monkeypatch.setattr(render, "check_tools", lambda: None)
    with TestClient(create_app(Settings(pair_code="T"), run_worker=False)) as c:
        c.headers["Authorization"] = "Bearer T"
        assert c.get(f"/api/training/{mid}").json()["video"] == {"state": "none"}
        assert c.get(f"/api/training/{mid}/video").status_code == 404
        assert c.post(f"/api/training/{mid}/render").status_code == 200
        for _ in range(50):
            if started:
                break
            time.sleep(0.02)
        assert started == [mid]
        assert c.get(f"/api/training/{mid}/render").json()["state"] == "ready"
        r = c.get(f"/api/training/{mid}/video", headers={"Range": "bytes=0-99"})
        assert r.status_code == 206 and len(r.content) == 100  # iPhone Safari needs ranges
        assert c.post("/api/training/999/render").status_code == 404
    with TestClient(create_app(Settings(pair_code="T"), run_worker=False)) as c:
        assert c.get(f"/api/training/{mid}/video").status_code == 401


def test_lock_spans_processes_and_frees_on_a_bad_module(monkeypatch):
    monkeypatch.setattr(render, "check_tools", lambda: None)
    held = render._RenderLock()
    assert held.acquire() and render.is_busy()
    with pytest.raises(render.Busy):
        render.render(1, MODULE)
    held.release()
    assert not render.is_busy()
    with pytest.raises(KeyError):
        render.render(1, {"title": "broken"})  # no lessons
    assert not render.is_busy()  # the lock was released
    assert render.status(1)["state"] == "failed"


def test_only_finished_clips_are_reused(tmp_path, monkeypatch):
    cache = tmp_path / "clips"
    cache.mkdir()
    (cache / "a_10_70.mp4.part").write_bytes(b"partial")
    (cache / "a_10_70.f137.mp4").write_bytes(b"video only")
    calls = []

    class FakeYDL:
        def __init__(self, opts):
            self.out = Path(opts["outtmpl"]).parent

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def download(self, urls):
            calls.append(urls)
            (self.out / "clip.mp4").write_bytes(b"merged")

    monkeypatch.setattr(render.yt_dlp, "YoutubeDL", FakeYDL)
    seg = render.Segment("clip", video_id="a", start=10, end=70)
    got = render.fetch_clip(seg, cache, "P")
    assert got == cache / "a_10_70.mp4" and got.read_bytes() == b"merged" and len(calls) == 1
    assert render.fetch_clip(seg, cache, "P") == got and len(calls) == 1  # cached
    assert not [d for d in cache.iterdir() if d.is_dir()]  # scratch folder removed


def test_old_clips_are_pruned(tmp_path):
    old, new = tmp_path / "old.mp4", tmp_path / "new.mp4"
    old.write_bytes(b"x")
    new.write_bytes(b"x")
    t = time.time() - 40 * 86400
    os.utime(old, (t, t))
    assert render.prune_clips(tmp_path) == 1 and new.exists() and not old.exists()


def test_screens_keep_a_lesson_without_clips():
    segs = render.plan(MODULE, {1: [("https://example.com", "")]}, max_clips=2)
    assert "screen" in kinds(segs)
