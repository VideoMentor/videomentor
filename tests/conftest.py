import pytest

from videomentor import db, library


@pytest.fixture(autouse=True)
def vm_home(tmp_path, monkeypatch):
    monkeypatch.setenv("VM_HOME", str(tmp_path / "lib"))
    return tmp_path / "lib"


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Tests never reach YouTube or Google; tests that need these replace them."""
    from videomentor import youtube_api
    from videomentor.sources import youtube

    def offline(*a, **k):
        raise RuntimeError("network disabled in tests")

    monkeypatch.setattr(youtube, "fetch_playlist_feed", lambda profile: [])
    monkeypatch.setattr(youtube, "fetch_playlist", offline)
    monkeypatch.setattr(youtube, "fetch_playlist_details", offline)
    monkeypatch.setattr(youtube_api, "_post_form", offline)
    monkeypatch.setattr(youtube_api, "_get_json", offline)


@pytest.fixture(autouse=True)
def no_llm_recorder():
    """Each test starts without the usage recorder that the app and CLI install."""
    from videomentor import llm

    llm.set_recorder(None)
    yield
    llm.set_recorder(None)


@pytest.fixture
def conn():
    c = db.connect()
    db.init(c)
    yield c
    c.close()


def add(
    conn, vid, *, topics=(), channel="Chan", category="learning", available=True, added="2026-01-01"
):
    """Insert a prepped inbox item."""
    library.upsert_item(
        conn,
        vid,
        source="youtube:watch_later",
        title=f"Video {vid}",
        channel=channel,
        added_at=f"{added}T00:00:00+00:00",
        available=available,
    )
    conn.execute(
        "UPDATE items SET prep_status = 'done', topics = ?, category = ?, why = 'because'"
        " WHERE id = ?",
        (library.dumps(list(topics)), category, f"yt:{vid}"),
    )
    conn.commit()
    return f"yt:{vid}"
