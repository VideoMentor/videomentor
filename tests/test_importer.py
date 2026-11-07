"""vm import-library: copy a library folder (for example from an older install) into VideoMentor."""

import os
import sqlite3
import stat

import pytest

from videomentor import db, library
from videomentor.importer import import_library


def make_source(root):
    """A small library: one item, one training module with an absolute path, the usual folders."""
    for sub in ("items", "training", "secrets", "logs", "web"):
        (root / sub).mkdir(parents=True, exist_ok=True)
    conn = db.connect(root / "library.db")
    db.init(conn)
    library.upsert_item(conn, "vid00000001", source="youtube:watch_later", title="A video")
    conn.execute(
        "INSERT INTO training_modules (tag, status, title, path, created_at) VALUES (?, 'ready', ?, ?, ?)",
        ("talks", "Talks", str(root / "training" / "m.md"), db.now()),
    )
    conn.commit()
    conn.close()
    (root / "items" / "a.md").write_text("# A video\n")
    (root / "training" / "m.md").write_text("# Talks\n")
    token = root / "secrets" / "token.json"
    token.write_text("{}")
    token.chmod(0o600)
    (root / "config.toml").write_text('# OldName settings.\npair_code = "1234-5678-9012"\n')
    (root / "logs" / "serve.log").write_text("log\n")
    (root / "web" / "index.html").write_text("<html></html>")
    return root


def snapshot(root):
    return {
        p.relative_to(root): (p.read_bytes(), p.stat().st_mtime_ns)
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


def test_copies_database_and_files(tmp_path):
    source, target = make_source(tmp_path / "OldName"), tmp_path / "VideoMentor"
    report = import_library(source, target)
    conn = sqlite3.connect(target / "library.db")
    assert conn.execute("SELECT title FROM items").fetchone()[0] == "A video"
    path = conn.execute("SELECT path FROM training_modules").fetchone()[0]
    assert path == str(target / "training" / "m.md")
    for rel in (
        "items/a.md",
        "training/m.md",
        "secrets/token.json",
        "config.toml",
        "logs/serve.log",
    ):
        assert (target / rel).exists(), rel
    assert not (target / "web").exists()  # rebuilt by install-service
    assert report.items == 1 and report.rewritten_paths == 1 and report.leftover_mentions == []
    assert report.files >= 5


def test_refuses_a_non_empty_target(tmp_path):
    source, target = make_source(tmp_path / "OldName"), tmp_path / "VideoMentor"
    target.mkdir()
    (target / "keep.txt").write_text("mine")
    before_source, before_target = snapshot(source), snapshot(target)
    with pytest.raises(ValueError):
        import_library(source, target)
    assert snapshot(source) == before_source and snapshot(target) == before_target


def test_leaves_the_source_untouched(tmp_path):
    source, target = make_source(tmp_path / "OldName"), tmp_path / "VideoMentor"
    before = snapshot(source)
    import_library(source, target)
    after = snapshot(source)
    assert {k: v for k, v in after.items() if k in before} == before


def test_includes_uncommitted_wal_writes(tmp_path):
    source, target = make_source(tmp_path / "OldName"), tmp_path / "VideoMentor"
    live = sqlite3.connect(source / "library.db")
    live.execute("PRAGMA journal_mode=WAL")
    live.execute("PRAGMA wal_autocheckpoint=0")
    live.execute("UPDATE items SET title = 'Renamed while running'")
    live.commit()  # committed to the WAL, not checkpointed into library.db
    try:
        import_library(source, target)
    finally:
        live.close()
    title = sqlite3.connect(target / "library.db").execute("SELECT title FROM items").fetchone()[0]
    assert title == "Renamed while running"


def test_secrets_keep_owner_only_permissions(tmp_path):
    source, target = make_source(tmp_path / "OldName"), tmp_path / "VideoMentor"
    import_library(source, target)
    mode = stat.S_IMODE(os.stat(target / "secrets" / "token.json").st_mode)
    assert mode == 0o600


def test_the_command_imports_into_a_fresh_library_home(tmp_path, monkeypatch, capsys):
    from videomentor import cli

    source = make_source(tmp_path / "OldName")
    home = tmp_path / "Fresh"
    monkeypatch.setenv("VM_HOME", str(home))
    cli.main(["import-library", str(source)])  # must not create config.toml before copying
    out = capsys.readouterr().out
    assert "1 videos" in out and "original folder is unchanged" in out
    assert (home / "library.db").exists() and (home / "config.toml").read_text().startswith(
        "# VideoMentor"
    )
