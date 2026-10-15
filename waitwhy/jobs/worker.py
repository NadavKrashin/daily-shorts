"""Job worker: claims jobs, runs handlers, heartbeats, shuts down gracefully on SIGTERM/SIGINT."""
from __future__ import annotations

import logging
import os
import signal
import socket
import threading
import time
from typing import Callable

from sqlalchemy.orm import Session

from waitwhy.db import session_factory
from waitwhy.jobs import queue
from waitwhy.models import WorkflowJob

log = logging.getLogger("waitwhy.worker")

Handler = Callable[[Session, WorkflowJob], dict | None]
HANDLERS: dict[str, Handler] = {}


def handler(job_type: str):
    def deco(fn: Handler) -> Handler:
        HANDLERS[job_type] = fn
        return fn
    return deco


class Worker:
    def __init__(self, worker_id: str | None = None, types: list[str] | None = None,
                 poll_interval: float = 2.0, heartbeat_interval: float = 15.0):
        from waitwhy.jobs import handlers  # noqa: F401  (registers handlers)

        self.worker_id = worker_id or f"{socket.gethostname()}:{os.getpid()}"
        self.types = types or list(HANDLERS)
        self.poll_interval = poll_interval
        self.heartbeat_interval = heartbeat_interval
        self._stop = threading.Event()
        self.Session = session_factory()

    # -- lifecycle -------------------------------------------------------------
    def install_signal_handlers(self) -> None:
        def _graceful(signum, _frame):
            log.info("worker %s received signal %s: finishing current job then exiting", self.worker_id, signum)
            self._stop.set()
        signal.signal(signal.SIGTERM, _graceful)
        signal.signal(signal.SIGINT, _graceful)

    def run_forever(self) -> None:
        self.install_signal_handlers()
        log.info("worker %s started (types=%s)", self.worker_id, ",".join(self.types))
        last_beat = 0.0
        while not self._stop.is_set():
            if time.monotonic() - last_beat > 30:
                self._beat()
                last_beat = time.monotonic()
            if not self.run_once():
                self._stop.wait(self.poll_interval)
        log.info("worker %s stopped", self.worker_id)

    def _beat(self) -> None:
        from datetime import datetime, timezone

        from waitwhy.models import SystemSetting
        s = self.Session()
        try:
            key = f"worker_heartbeat:{self.worker_id}"
            row = s.get(SystemSetting, key)
            stamp = datetime.now(timezone.utc).isoformat()
            if row:
                row.value = stamp
            else:
                s.add(SystemSetting(key=key, value=stamp, updated_by=self.worker_id))
            s.commit()
        except Exception as exc:  # noqa: BLE001
            log.warning("worker heartbeat failed: %s", exc)
            s.rollback()
        finally:
            s.close()

    def run_until_idle(self, max_jobs: int = 500) -> int:
        """Process jobs until none are runnable now. Used by tests, demos and the CLI."""
        n = 0
        while n < max_jobs and self.run_once():
            n += 1
        return n

    # -- execution -------------------------------------------------------------
    def run_once(self) -> bool:
        claim_session = self.Session()
        try:
            job = queue.claim(claim_session, self.worker_id, self.types)
        finally:
            claim_session.close()
        if job is None:
            return False
        self._execute(job.id)
        return True

    def _execute(self, job_id) -> None:
        stop_hb = threading.Event()
        hb = threading.Thread(target=self._heartbeat_loop, args=(job_id, stop_hb), daemon=True)
        hb.start()
        session = self.Session()
        started = time.monotonic()
        try:
            job = session.get(WorkflowJob, job_id)
            fn = HANDLERS.get(job.type)
            if fn is None:
                raise queue.WaitWhyError(f"no handler registered for job type {job.type}")
            log.info("job %s %s attempt %s/%s", job.id, job.type, job.attempts, job.max_attempts)
            result = fn(session, job) or {}
            session.commit()
            queue.complete(session, session.get(WorkflowJob, job_id), result)
            log.info("job %s %s succeeded in %.1fs", job_id, job.type, time.monotonic() - started)
        except BaseException as exc:  # noqa: BLE001 - classify everything, never crash the worker
            session.rollback()
            job = session.get(WorkflowJob, job_id, populate_existing=True)
            queue.fail(session, job, exc)
            if isinstance(exc, KeyboardInterrupt):
                raise
        finally:
            stop_hb.set()
            session.close()

    def _heartbeat_loop(self, job_id, stop: threading.Event) -> None:
        s = self.Session()
        try:
            while not stop.wait(self.heartbeat_interval):
                try:
                    queue.heartbeat(s, job_id)
                except Exception as exc:  # noqa: BLE001
                    log.warning("heartbeat failed for %s: %s", job_id, exc)
                    s.rollback()
        finally:
            s.close()
