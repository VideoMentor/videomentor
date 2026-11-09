"""Background work inside ``vm serve``.

Four threads, so a big prep backlog never delays a prioritized analysis:
- sync: Watch Later and bookmarks every ``sync_interval_hours``, or on request
- prep: metadata enrichment, then card prep
- analysis: prioritized items as soon as they arrive, kept items at a trickle
- backup: a daily copy of the library, checked once an hour
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import UTC, datetime

from . import ai, analyze, backup, db, llm, prep, scoring, sync, tagging
from .config import Settings, library_home

log = logging.getLogger(__name__)


class Worker:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.stop = threading.Event()
        self.sync_now = threading.Event()
        self.work_now = threading.Event()
        self.analyze_now = threading.Event()
        self.state: dict = {"sync": "idle", "prep": "idle", "analysis": "idle", "last_error": None}
        self._last_trickle = 0.0
        self._threads: list[threading.Thread] = []

    def start(self) -> None:
        for name, target in (
            ("sync", self._sync_loop),
            ("prep", self._prep_loop),
            ("analysis", self._analysis_loop),
            ("backup", self._backup_loop),
        ):
            t = threading.Thread(target=target, name=f"vm-{name}", daemon=True)
            t.start()
            self._threads.append(t)

    def shutdown(self) -> None:
        self.stop.set()
        for e in (self.sync_now, self.work_now, self.analyze_now):
            e.set()

    def _error(self, where: str, e: Exception) -> None:
        log.exception("%s failed", where)
        self.state["last_error"] = {"where": where, "error": str(e)[:300], "at": db.now()}

    def _sync_loop(self) -> None:
        interval = self.settings.sync_interval_hours * 3600
        with db.session() as conn:
            last = sync.last_sync(conn)
        due_in = 0.0
        if last:
            age = (datetime.now(UTC) - datetime.fromisoformat(last["finished_at"])).total_seconds()
            due_in = max(0.0, interval - age)
        self.sync_now.wait(due_in)
        while not self.stop.is_set():
            self.sync_now.clear()
            self.state["sync"] = "running"
            try:
                with db.session() as conn:
                    sync.run_sync(conn, self.settings)
                self.work_now.set()
            except Exception as e:  # noqa: BLE001
                self._error("sync", e)
            self.state["sync"] = "idle"
            self.sync_now.wait(interval)

    def backup_tick(self) -> None:
        """Make and prune a backup when one is due. Never raises: a failure is only logged."""
        try:
            home = library_home()
            if not (home / "library.db").exists():
                return
            if backup.due(home, datetime.now().astimezone()):
                self.state["backup"] = "running"
                backup.make_backup(home)
                backup.prune(home)
        except Exception as e:  # noqa: BLE001
            log.exception("backup failed")
            self.state["backup_error"] = {"where": "backup", "error": str(e)[:300], "at": db.now()}
        else:
            self.state["backup_error"] = None
        finally:
            self.state["backup"] = "idle"

    def _backup_loop(self) -> None:
        while not self.stop.is_set():
            self.backup_tick()
            self.stop.wait(3600)

    def _ai_ok(self, conn) -> bool:
        """Whether AI may run now. When it may not, the reason shows in ``ai.status``."""
        ok, _ = ai.allowed(conn, self.settings)
        return ok

    def prep_tick(self) -> int:
        """One pass of enrichment, then card prep, tagging and scoring (when AI may run)."""
        did = 0
        with db.session() as conn:
            self.state["prep"] = "enriching"
            did += sync.enrich_pending(conn, self.settings)
            self.state["prep"] = "prepping"
            batch = prep.pending(conn, self.settings.prep_batch_size)
            if batch and self._ai_ok(conn):
                did += prep.prep_batch(conn, batch, self.settings.prep_model)
            self.state["prep"] = "tagging"
            batch = tagging.pending(conn, self.settings.prep_batch_size)
            if batch and self._ai_ok(conn):
                did += tagging.tag_batch(conn, batch, self.settings.prep_model)
            self.state["prep"] = "scoring"
            batch = scoring.pending(conn, self.settings.prep_batch_size)
            if batch and self._ai_ok(conn):
                did += scoring.score_batch(
                    conn,
                    batch,
                    self.settings.prep_model,
                    scoring.rules(self.settings.signal_areas, self.settings.signal_guidance),
                )
        return did

    def _prep_loop(self) -> None:
        backoff = 0.0
        while not self.stop.is_set():
            did = 0
            try:
                did = self.prep_tick()
                backoff = 0.0
            except llm.LLMError as e:
                self._error("prep", e)
                backoff = min(max(backoff * 2, 30.0), 900.0)
            except Exception as e:  # noqa: BLE001
                self._error("prep", e)
                backoff = 60.0
            self.state["prep"] = "idle"
            if backoff:
                self.work_now.wait(backoff)
            elif not did:
                self.work_now.wait(300)
            self.work_now.clear()

    def analysis_tick(self) -> dict | None:
        """Analyze the next due item, if AI may run. Returns the item it worked on."""
        trickle = self.settings.kept_trickle_minutes * 60
        item = None
        with db.session() as conn:
            if not self._ai_ok(conn):
                return None
            candidate = analyze.next_item(conn)
            if candidate and (
                candidate["priority"] or time.monotonic() - self._last_trickle >= trickle
            ):
                item = candidate
            if item:
                self.state["analysis"] = f"analyzing {item['id']}"
                try:
                    analyze.analyze_item(
                        conn,
                        item,
                        chrome_profile=self.settings.watch_later_profile,
                        model=self.settings.analysis_model,
                        skills=self.settings.skill_map,
                        signal_rules=scoring.rules(
                            self.settings.signal_areas, self.settings.signal_guidance
                        ),
                    )
                except Exception as e:  # noqa: BLE001
                    self._error(f"analysis {item['id']}", e)
                if not item["priority"]:
                    self._last_trickle = time.monotonic()
        return item

    def _analysis_loop(self) -> None:
        with db.session() as conn:
            # A crash mid-analysis leaves items "running"; put them back in the queue.
            conn.execute(
                "UPDATE items SET analysis_status = 'queued' WHERE analysis_status = 'running'"
            )
        while not self.stop.is_set():
            self.analyze_now.clear()
            item = self.analysis_tick()
            self.state["analysis"] = "idle"
            if not item:
                self.analyze_now.wait(60)
