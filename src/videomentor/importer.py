"""Copy a library folder (for example from an older install) into VideoMentor.

The source is never changed: it stays as the backup. The database is copied with
SQLite's backup API, so the copy is consistent even while the old app is running
(including writes still in its WAL file). The installed web app (`web/`) is not
copied; `vm install-service` rebuilds it.
"""

from __future__ import annotations

import shutil
import socket
import sqlite3
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

FOLDERS = ("items", "training", "secrets", "logs")
FILES = ("config.toml",)


@dataclass
class ImportReport:
    items: int = 0
    files: int = 0
    rewritten_paths: int = 0
    leftover_mentions: list[str] = field(default_factory=list)


def import_library(source: Path, target: Path) -> ImportReport:
    """Copy the library at `source` into `target`, which must be missing or empty.

    Built in a temporary folder next to the target and moved into place at the end, so a
    failure partway through leaves nothing behind and a retry starts clean.
    """
    source, target = Path(source).expanduser().resolve(), Path(target).expanduser().resolve()
    if not (source / "library.db").exists():
        raise ValueError(f"No library at {source} (library.db is missing)")
    if target.exists() and any(target.iterdir()):
        raise ValueError(f"{target} already has files in it; it must be empty")
    if target == source or source in target.parents:
        raise ValueError("The target can't be the source folder or inside it")
    _refuse_if_running(source)

    work = target.parent / f".{target.name}.importing"
    shutil.rmtree(work, ignore_errors=True)  # left by an interrupted earlier run
    work.mkdir(parents=True)
    try:
        report = _copy(source, work, rewrite_to=target)
        if target.exists():
            target.rmdir()  # empty, checked above
        work.rename(target)
    except BaseException:
        shutil.rmtree(work, ignore_errors=True)
        raise
    return report


def _refuse_if_running(source: Path) -> None:
    """The old app still serving means writes could land after the copy: stop first."""
    try:
        port = int(tomllib.loads((source / "config.toml").read_text()).get("port", 0))
    except (OSError, ValueError, tomllib.TOMLDecodeError):
        return
    if not port:
        return
    with socket.socket() as s:
        s.settimeout(0.5)
        if s.connect_ex(("127.0.0.1", port)) == 0:
            raise ValueError(
                f"The app using {source} is still running (port {port}). Stop its login service"
                " first (for example its `uninstall-service` command), then import."
            )


def _copy(source: Path, work: Path, rewrite_to: Path) -> ImportReport:
    report = ImportReport()
    sidecars = [source / "library.db-wal", source / "library.db-shm"]
    existed = {p for p in sidecars if p.exists()}
    src = sqlite3.connect(f"{source.as_uri()}/library.db?mode=ro", uri=True)
    dst = sqlite3.connect(work / "library.db")
    try:
        src.backup(dst)
    finally:
        src.close()
        # A read-only open of an idle WAL database creates empty -wal/-shm files; the
        # source must be left exactly as it was, so remove any this run created.
        for p in sidecars:
            if p not in existed and p.exists():
                p.unlink()
    report.files += 1
    try:
        for name in FOLDERS:
            if (source / name).is_dir():
                shutil.copytree(source / name, work / name, copy_function=shutil.copy2)
                report.files += sum(1 for p in (work / name).rglob("*") if p.is_file())
        for name in FILES:
            if (source / name).is_file():
                shutil.copy2(source / name, work / name)
                report.files += 1
        old, new = str(source), str(rewrite_to)
        with dst:
            cur = dst.execute(
                "UPDATE training_modules SET path = ? || substr(path, ?) WHERE path LIKE ? || '%'",
                (new, len(old) + 1, old),
            )
            report.rewritten_paths = cur.rowcount
        report.items = dst.execute("SELECT COUNT(*) FROM items").fetchone()[0]
        report.leftover_mentions = _mentions(dst, old)
    finally:
        dst.close()

    config = work / "config.toml"
    if config.exists():
        lines = config.read_text().splitlines(keepends=True)
        if lines and lines[0].startswith("#"):
            lines[0] = "# VideoMentor settings. See docs/setup.md for what each one does.\n"
            config.write_text("".join(lines))
    return report


def _mentions(conn: sqlite3.Connection, prefix: str) -> list[str]:
    """table.column names whose text still contains `prefix`."""
    found = []
    tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")]
    for table in tables:
        for _, col, kind, *_ in conn.execute(f'PRAGMA table_info("{table}")'):
            if kind.upper() not in ("TEXT", ""):
                continue
            hit = conn.execute(
                f'SELECT 1 FROM "{table}" WHERE instr("{col}", ?) > 0 LIMIT 1', (prefix,)
            ).fetchone()
            if hit:
                found.append(f"{table}.{col}")
    return found
