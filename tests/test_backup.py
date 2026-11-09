"""Daily library backups: backup.py, the worker hook, `vm backup` and /api/status."""

import gzip
import os
import sqlite3
import tarfile
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from videomentor import backup, cli, db, library
from videomentor.api import create_app
from videomentor.config import load_settings
from videomentor.worker import Worker

NOW = datetime(2026, 11, 9, 3, 0).astimezone()


def make_home(tmp_path, *, wal=False):
    home = tmp_path / "home"
    home.mkdir()
    conn = db.connect(home / "library.db")
    db.init(conn)
    library.upsert_item(conn, "vid00000001", source="youtube:watch_later", title="One")
    library.upsert_item(conn, "vid00000002", source="youtube:watch_later", title="Two")
    conn.commit()
    if wal:
        conn.execute("PRAGMA wal_autocheckpoint=0")
        conn.execute("UPDATE items SET title = 'Changed in the WAL' WHERE id = 'yt:vid00000001'")
        conn.commit()
        return home, conn
    conn.close()
    return home, None


def restore(path, out):
    out.write_bytes(gzip.decompress(path.read_bytes()))
    return sqlite3.connect(out)


def fake_backup(home, day, kind="library", ext="db.gz"):
    d = home / "backups"
    d.mkdir(exist_ok=True)
    p = d / f"{kind}-{day}.{ext}"
    p.write_bytes(b"x" * 10)
    return p


def test_backup_restores_to_a_valid_database_with_same_rows(tmp_path):
    home, _ = make_home(tmp_path)
    path = backup.make_backup(home, NOW)
    assert path == home / "backups" / "library-2026-11-09.db.gz"
    c = restore(path, tmp_path / "restored.db")
    assert c.execute("PRAGMA quick_check").fetchone()[0] == "ok"
    assert c.execute("SELECT COUNT(*) FROM items").fetchone()[0] == 2


def test_backup_includes_writes_still_in_the_wal(tmp_path):
    home, live = make_home(tmp_path, wal=True)
    try:
        path = backup.make_backup(home, NOW)
    finally:
        live.close()
    c = restore(path, tmp_path / "restored.db")
    assert c.execute("SELECT title FROM items WHERE id = 'yt:vid00000001'").fetchone()[0] == (
        "Changed in the WAL"
    )


def test_backup_leaves_only_final_files(tmp_path):
    home, _ = make_home(tmp_path)
    (home / "training").mkdir()
    (home / "training" / "m.md").write_text("module")
    backup.make_backup(home, NOW)
    names = sorted(p.name for p in (home / "backups").iterdir())
    assert names == ["library-2026-11-09.db.gz", "training-2026-11-09.tar.gz"]
    assert not (home / "library.db-wal").exists() and not (home / "library.db-shm").exists()


def test_same_day_backup_replaces_the_file(tmp_path):
    home, _ = make_home(tmp_path)
    backup.make_backup(home, NOW)
    conn = sqlite3.connect(home / "library.db")
    conn.execute("DELETE FROM items WHERE id = 'yt:vid00000002'")
    conn.commit()
    conn.close()
    path = backup.make_backup(home, NOW + timedelta(hours=2))
    assert len(list((home / "backups").glob("library-*"))) == 1
    c = restore(path, tmp_path / "restored.db")
    assert c.execute("SELECT COUNT(*) FROM items").fetchone()[0] == 1


def test_training_folder_is_tarred_only_when_it_has_files(tmp_path):
    home, _ = make_home(tmp_path)
    backup.make_backup(home, NOW)
    assert not list((home / "backups").glob("training-*"))
    (home / "training").mkdir()
    backup.make_backup(home, NOW)
    assert not list((home / "backups").glob("training-*"))
    (home / "training" / "m.md").write_text("module")
    backup.make_backup(home, NOW)
    with tarfile.open(home / "backups" / "training-2026-11-09.tar.gz") as t:
        assert "training/m.md" in t.getnames()


def test_secrets_and_items_are_not_backed_up(tmp_path):
    home, _ = make_home(tmp_path)
    for name in ("secrets", "items", "training"):
        (home / name).mkdir()
        (home / name / "f.txt").write_text("TOPSECRET")
    backup.make_backup(home, NOW)
    for p in (home / "backups").iterdir():
        data = gzip.decompress(p.read_bytes())
        assert b"TOPSECRET" not in data or p.name.startswith("training-")
        if p.name.startswith("training-"):
            with tarfile.open(p) as t:
                assert all(n.startswith("training") for n in t.getnames())
                assert not any("secrets" in n or "items" in n for n in t.getnames())


def test_a_corrupt_database_raises_and_leaves_no_backup(tmp_path, monkeypatch):
    home, _ = make_home(tmp_path)
    monkeypatch.setattr(backup, "_quick_check", lambda path: "database disk image is malformed")
    with pytest.raises(RuntimeError, match="quick_check"):
        backup.make_backup(home, NOW)
    assert list((home / "backups").iterdir()) == []


def test_prune_keeps_the_newest_14_days_of_both_kinds(tmp_path):
    home, _ = make_home(tmp_path)
    for i in range(20):
        day = (NOW - timedelta(days=i)).strftime("%Y-%m-%d")
        fake_backup(home, day)
        fake_backup(home, day, "training", "tar.gz")
    removed = backup.prune(home)
    assert removed == 12
    assert len(list((home / "backups").glob("library-*"))) == 14
    assert len(list((home / "backups").glob("training-*"))) == 14
    oldest_kept = (NOW - timedelta(days=13)).strftime("%Y-%m-%d")
    assert (home / "backups" / f"library-{oldest_kept}.db.gz").exists()
    assert not (home / "backups" / f"library-{(NOW - timedelta(days=14)):%Y-%m-%d}.db.gz").exists()


def test_prune_with_nothing_to_do(tmp_path):
    home, _ = make_home(tmp_path)
    assert backup.prune(home) == 0


def test_due(tmp_path):
    home, _ = make_home(tmp_path)
    assert backup.due(home, NOW)  # none yet
    p = fake_backup(home, "2026-11-09")
    os.utime(p, (NOW.timestamp() - 3 * 3600,) * 2)
    assert not backup.due(home, NOW)
    os.utime(p, (NOW.timestamp() - 21 * 3600,) * 2)
    assert backup.due(home, NOW)


def test_summary(tmp_path):
    home, _ = make_home(tmp_path)
    assert backup.summary(home) == {"last_at": None, "count": 0, "bytes": 0}
    p = fake_backup(home, "2026-11-08")
    fake_backup(home, "2026-11-09")
    fake_backup(home, "2026-11-09", "training", "tar.gz")
    os.utime(p, (NOW.timestamp(),) * 2)
    s = backup.summary(home)
    assert s["count"] == 2 and s["bytes"] == 30
    assert datetime.fromisoformat(s["last_at"])


def test_worker_hook_makes_a_backup_when_due_and_prunes(tmp_path, monkeypatch):
    home, _ = make_home(tmp_path)
    monkeypatch.setenv("VM_HOME", str(home))
    for i in range(1, 20):
        p = fake_backup(home, (NOW - timedelta(days=i)).strftime("%Y-%m-%d"))
        os.utime(p, (NOW.timestamp() - i * 86400,) * 2)
    w = Worker(load_settings())
    w.backup_tick()
    assert len(list((home / "backups").glob("library-*"))) == 14
    assert w.state["last_error"] is None


def test_worker_hook_failure_is_logged_and_never_raises(tmp_path, monkeypatch):
    monkeypatch.setenv("VM_HOME", str(tmp_path / "home"))
    w = Worker(load_settings())

    def boom(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(backup, "make_backup", boom)
    w.backup_tick()  # no database, then a failing backup: neither may raise
    (tmp_path / "home").mkdir(exist_ok=True)
    db.connect(tmp_path / "home" / "library.db").close()
    w.backup_tick()
    assert w.state["last_error"]["where"] == "backup"
    assert "disk full" in w.state["last_error"]["error"]


def test_cli_backup_and_list(tmp_path, monkeypatch, capsys):
    home, _ = make_home(tmp_path)
    monkeypatch.setenv("VM_HOME", str(home))
    cli.main(["backup"])
    out = capsys.readouterr().out
    today = datetime.now().strftime("%Y-%m-%d")
    assert f"library-{today}.db.gz" in out
    fake_backup(home, "2026-01-01")
    cli.main(["backup", "--list"])
    lines = capsys.readouterr().out.strip().splitlines()
    assert f"library-{today}.db.gz" in lines[0]
    assert "library-2026-01-01.db.gz" in lines[1]


def test_cli_list_with_no_backups(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("VM_HOME", str(tmp_path / "home"))
    cli.main(["backup", "--list"])
    assert "No backups yet" in capsys.readouterr().out


def test_status_api_has_backups(conn):
    settings = load_settings()
    with TestClient(create_app(settings, run_worker=False)) as c:
        c.get(f"/pair?code={settings.pair_code}", follow_redirects=False)
        assert c.get("/api/status").json()["backups"] == {"last_at": None, "count": 0, "bytes": 0}
