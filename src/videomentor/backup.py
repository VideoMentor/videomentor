"""Daily backups of the library: ``library.db`` and ``training/``.

Files live in ``<home>/backups`` as ``library-YYYY-MM-DD.db.gz`` and, when the
training folder has files, ``training-YYYY-MM-DD.tar.gz``. ``secrets/`` (tokens,
cookies) is never included, and neither is ``items/`` (``vm export`` rebuilds it).
"""

from __future__ import annotations

import gzip
import os
import re
import shutil
import sqlite3
import tarfile
import tempfile
from datetime import datetime
from pathlib import Path

DIR = "backups"
DUE_AFTER_HOURS = 20
_NAME = re.compile(r"^(library|training)-(\d{4}-\d{2}-\d{2})\.(db|tar)\.gz$")


def _quick_check(path: Path) -> str:
    conn = sqlite3.connect(path)
    try:
        return str(conn.execute("PRAGMA quick_check").fetchone()[0])
    finally:
        conn.close()


def _files(home: Path) -> list[tuple[str, Path]]:
    """(day, path) for every finished backup file."""
    d = home / DIR
    if not d.is_dir():
        return []
    return [(m.group(2), p) for p in d.iterdir() if (m := _NAME.match(p.name))]


def _snapshot_db(home: Path, dest: Path) -> None:
    sidecars = [home / "library.db-wal", home / "library.db-shm"]
    existed = {p for p in sidecars if p.exists()}
    src = sqlite3.connect(f"{home.as_uri()}/library.db?mode=ro", uri=True)
    dst = sqlite3.connect(dest)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
        # A read-only open of an idle WAL database can create empty -wal/-shm files.
        for p in sidecars:
            if p not in existed and p.exists():
                p.unlink()


def _has_files(folder: Path) -> bool:
    return folder.is_dir() and any(p.is_file() for p in folder.rglob("*"))


def make_backup(home: Path, now: datetime | None = None) -> Path:
    """Write today's backup (replacing one from earlier today) and return the database file."""
    now = now or datetime.now().astimezone()
    day = now.strftime("%Y-%m-%d")
    out = home / DIR
    out.mkdir(parents=True, exist_ok=True)
    final = out / f"library-{day}.db.gz"
    temps: list[Path] = []

    def temp(suffix: str) -> Path:
        fd, name = tempfile.mkstemp(prefix=".tmp-", suffix=suffix, dir=out)
        os.close(fd)
        temps.append(Path(name))
        return temps[-1]

    try:
        raw = temp(".db")
        _snapshot_db(home, raw)
        result = _quick_check(raw)
        if result != "ok":
            raise RuntimeError(f"Backup copy failed PRAGMA quick_check: {result}")
        gz = temp(".gz")
        with raw.open("rb") as f_in, gzip.open(gz, "wb") as f_out:
            shutil.copyfileobj(f_in, f_out)
        tar_tmp = None
        if _has_files(home / "training"):
            tar_tmp = temp(".tar.gz")
            with tarfile.open(tar_tmp, "w:gz") as t:
                t.add(home / "training", arcname="training")
        os.replace(gz, final)
        if tar_tmp:
            os.replace(tar_tmp, out / f"training-{day}.tar.gz")
    finally:
        for p in temps:
            p.unlink(missing_ok=True)
    return final


def prune(home: Path, keep: int = 14) -> int:
    """Keep the newest ``keep`` days of backups; return how many files were removed."""
    files = _files(home)
    days = sorted({d for d, _ in files}, reverse=True)
    old = set(days[keep:])
    removed = 0
    for day, p in files:
        if day in old:
            p.unlink(missing_ok=True)
            removed += 1
    return removed


def _newest_mtime(home: Path) -> float | None:
    times = [p.stat().st_mtime for _, p in _files(home) if p.name.startswith("library-")]
    return max(times) if times else None


def due(home: Path, now: datetime) -> bool:
    """True when no database backup was written in the last 20 hours."""
    newest = _newest_mtime(home)
    return newest is None or now.timestamp() - newest >= DUE_AFTER_HOURS * 3600


def summary(home: Path) -> dict:
    files = _files(home)
    newest = _newest_mtime(home)
    return {
        "last_at": datetime.fromtimestamp(newest).astimezone().isoformat() if newest else None,
        "count": len({d for d, _ in files}),
        "bytes": sum(p.stat().st_size for _, p in files),
    }


def listing(home: Path) -> list[tuple[Path, int]]:
    """Backup files, newest day first, with sizes."""
    return [
        (p, p.stat().st_size)
        for _, p in sorted(_files(home), key=lambda t: (t[0], t[1].name), reverse=True)
    ]
