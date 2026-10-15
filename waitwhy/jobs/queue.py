"""Durable Postgres job queue.

* Claiming uses ``SELECT ... FOR UPDATE SKIP LOCKED`` so any number of workers can run safely.
* ``idempotency_key`` is UNIQUE: enqueueing the same logical job twice returns the existing row.
* Retries: transient errors back off exponentially with jitter; permanent/auth/policy errors go
  straight to ``dead`` (the dead-letter state) and raise an alert.
* Budget/approval stops park the job as ``blocked`` without consuming an attempt; nothing is lost.
* ``recover_stalled`` re-queues jobs whose worker died (stale heartbeat) - job recovery after restart.
"""
from __future__ import annotations

import logging
import random
import traceback
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from waitwhy.errors import (
    ApprovalRequired,
    AutomationPaused,
    BudgetExceeded,
    TransientError,
    WaitWhyError,
)
from waitwhy.models import WorkflowJob

log = logging.getLogger("waitwhy.queue")


@dataclass(frozen=True)
class JobSpec:
    timeout_s: int = 900
    max_attempts: int = 5
    concurrency: int = 4
    priority: int = 0
    essential: bool = False      # still runs while automation is paused (health, reports, recovery)
    publishing: bool = False     # blocked by the emergency "Pause All Publishing" switch


JOB_SPECS: dict[str, JobSpec] = {
    # operations
    "health_check": JobSpec(timeout_s=300, max_attempts=2, essential=True, priority=50),
    "recover_stalled": JobSpec(timeout_s=120, max_attempts=1, essential=True, priority=60),
    "analytics_collect": JobSpec(timeout_s=1200, max_attempts=3, essential=True, concurrency=1),
    "strategy_analysis": JobSpec(timeout_s=900, max_attempts=2, essential=True, concurrency=1),
    "content_planning": JobSpec(timeout_s=900, max_attempts=2, concurrency=1),
    "daily_report": JobSpec(timeout_s=600, max_attempts=3, essential=True, concurrency=1, priority=40),
    "weekly_review": JobSpec(timeout_s=900, max_attempts=3, essential=True, concurrency=1),
    "monthly_review": JobSpec(timeout_s=900, max_attempts=3, essential=True, concurrency=1),
    "db_backup": JobSpec(timeout_s=1800, max_attempts=2, essential=True, concurrency=1),
    "production_tick": JobSpec(timeout_s=300, max_attempts=1, concurrency=1),
    # content pipeline
    "trend_discovery": JobSpec(timeout_s=1200, max_attempts=3, concurrency=1),
    "start_production": JobSpec(timeout_s=120, max_attempts=3),
    "research": JobSpec(timeout_s=1800, max_attempts=3, concurrency=2),
    "script": JobSpec(timeout_s=900, max_attempts=3, concurrency=2),
    "storyboard": JobSpec(timeout_s=900, max_attempts=3, concurrency=2),
    "generate_assets": JobSpec(timeout_s=3600, max_attempts=4, concurrency=2),
    "edit": JobSpec(timeout_s=1800, max_attempts=3, concurrency=1),
    "qc": JobSpec(timeout_s=900, max_attempts=3, concurrency=2),
    "prepare_metadata": JobSpec(timeout_s=300, max_attempts=3),
    "schedule_publications": JobSpec(timeout_s=120, max_attempts=3, publishing=True),
    "publish": JobSpec(timeout_s=1800, max_attempts=5, concurrency=2, publishing=True),
    "publish_due": JobSpec(timeout_s=300, max_attempts=1, concurrency=1, publishing=True, essential=True),
    "sponsor_research": JobSpec(timeout_s=1200, max_attempts=2, concurrency=1),
}
DEFAULT_SPEC = JobSpec()


def spec_for(job_type: str) -> JobSpec:
    return JOB_SPECS.get(job_type, DEFAULT_SPEC)


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def enqueue(
    session: Session,
    job_type: str,
    payload: dict[str, Any] | None = None,
    *,
    idempotency_key: str | None = None,
    run_at: datetime | None = None,
    priority: int | None = None,
    video_id: uuid.UUID | None = None,
    max_attempts: int | None = None,
) -> WorkflowJob:
    spec = spec_for(job_type)
    values = dict(
        id=uuid.uuid4(),
        type=job_type,
        payload=payload or {},
        status="queued",
        priority=spec.priority if priority is None else priority,
        run_at=run_at or now_utc(),
        attempts=0,
        max_attempts=max_attempts or spec.max_attempts,
        timeout_s=spec.timeout_s,
        idempotency_key=idempotency_key,
        video_id=video_id,
        created_at=now_utc(),
    )
    if idempotency_key:
        stmt = pg_insert(WorkflowJob).values(**values).on_conflict_do_nothing(index_elements=["idempotency_key"])
        session.execute(stmt)
        session.flush()
        return session.execute(
            select(WorkflowJob).where(WorkflowJob.idempotency_key == idempotency_key)
        ).scalar_one()
    job = WorkflowJob(**values)
    session.add(job)
    session.flush()
    return job


def _paused_flags(session: Session) -> tuple[bool, bool]:
    rows = session.execute(
        text("SELECT key, value FROM system_settings WHERE key IN ('automation_paused','publishing_paused')")
    ).all()
    flags = {k: bool(v) for k, v in rows}
    return flags.get("automation_paused", False), flags.get("publishing_paused", False)


def claim(session: Session, worker_id: str, types: list[str] | None = None) -> WorkflowJob | None:
    """Atomically claim the next runnable job. Commits immediately."""
    automation_paused, publishing_paused = _paused_flags(session)
    running = dict(
        session.execute(
            select(WorkflowJob.type, func.count()).where(WorkflowJob.status == "running").group_by(WorkflowJob.type)
        ).all()
    )
    candidates = types or list(JOB_SPECS)
    allowed = []
    for t in candidates:
        spec = spec_for(t)
        if running.get(t, 0) >= spec.concurrency:
            continue
        if automation_paused and not spec.essential:
            continue
        if publishing_paused and spec.publishing:
            continue
        allowed.append(t)
    if not allowed:
        return None
    sub = (
        select(WorkflowJob.id)
        .where(WorkflowJob.status == "queued", WorkflowJob.run_at <= now_utc(), WorkflowJob.type.in_(allowed))
        .order_by(WorkflowJob.priority.desc(), WorkflowJob.run_at)
        .limit(1)
        .with_for_update(skip_locked=True)
        .scalar_subquery()
    )
    stmt = (
        update(WorkflowJob)
        .where(WorkflowJob.id == sub)
        .values(status="running", locked_by=worker_id, locked_at=now_utc(), heartbeat_at=now_utc(),
                attempts=WorkflowJob.attempts + 1)
        .returning(WorkflowJob.id)
    )
    job_id = session.execute(stmt).scalar_one_or_none()
    session.commit()
    if job_id is None:
        return None
    return session.get(WorkflowJob, job_id, populate_existing=True)


def heartbeat(session: Session, job_id: uuid.UUID) -> None:
    session.execute(update(WorkflowJob).where(WorkflowJob.id == job_id, WorkflowJob.status == "running")
                    .values(heartbeat_at=now_utc()))
    session.commit()


def complete(session: Session, job: WorkflowJob, result: dict | None = None) -> None:
    job.status = "succeeded"
    job.result = result or {}
    job.finished_at = now_utc()
    job.locked_by = None
    job.last_error = None
    session.commit()


def backoff_seconds(attempt: int, base: float = 30.0, cap: float = 3600.0) -> float:
    delay = min(cap, base * (2 ** max(0, attempt - 1)))
    return delay * (0.75 + random.random() * 0.5)  # +/-25 % jitter


def fail(session: Session, job: WorkflowJob, exc: BaseException) -> str:
    """Record a failure and decide: retry, park (blocked), or dead-letter. Returns new status."""
    from waitwhy.notify import alert  # local import: notify depends on models only

    err = f"{type(exc).__name__}: {exc}"
    job.last_error = err[:4000]
    job.locked_by = None
    job.error_class = getattr(exc, "error_class", "unexpected")
    if isinstance(exc, (BudgetExceeded, ApprovalRequired)):
        job.status = "blocked"
        job.attempts = max(0, job.attempts - 1)  # parking is not a failed attempt
    elif isinstance(exc, AutomationPaused):
        job.status = "queued"
        job.attempts = max(0, job.attempts - 1)
        job.run_at = now_utc() + timedelta(minutes=5)
    elif (isinstance(exc, TransientError) or not isinstance(exc, WaitWhyError)) and job.attempts < job.max_attempts:
        # Unknown exceptions are treated as transient (bounded by max_attempts) and fully logged.
        retry_after = getattr(exc, "retry_after_s", None)
        job.status = "queued"
        job.run_at = now_utc() + timedelta(seconds=retry_after or backoff_seconds(job.attempts))
    else:
        job.status = "dead"
        job.finished_at = now_utc()
        severity = "high" if job.error_class in ("auth", "policy") else "low"
        if job.type in ("publish", "edit", "generate_assets") and job.error_class not in ("auth", "policy"):
            severity = "high"
        alert(session, severity, f"job.{job.type}", f"Job {job.type} failed permanently", err,
              dedupe_key=f"job-dead:{job.type}:{job.error_class}:{job.video_id}", video_id=job.video_id)
        if job.video_id and job.type not in ("publish", "schedule_publications"):
            _fail_video(session, job, err)
    if not isinstance(exc, WaitWhyError):
        log.error("job %s (%s) crashed:\n%s", job.id, job.type, "".join(traceback.format_exception(exc)))
    else:
        log.warning("job %s (%s) -> %s: %s", job.id, job.type, job.status, err)
    session.commit()
    return job.status


def _fail_video(session: Session, job: WorkflowJob, err: str) -> None:
    """A dead pipeline job makes its video visibly FAILED (unless it already sits in a side state)."""
    from waitwhy.errors import InvalidTransition
    from waitwhy.models import Video
    from waitwhy.states import S, transition

    video = session.get(Video, job.video_id)
    if video is None or video.state in (S.NEEDS_REVISION.value, S.BLOCKED.value, S.FAILED.value, S.CANCELLED.value):
        return
    try:
        transition(session, video, S.FAILED, "system:queue", f"{job.type} failed: {err[:300]}")
    except InvalidTransition:
        pass


def recover_stalled(session: Session, grace_s: int = 120) -> int:
    """Re-queue running jobs whose heartbeat is older than their timeout (worker crashed/killed)."""
    count = 0
    now = now_utc()
    rows = session.execute(select(WorkflowJob).where(WorkflowJob.status == "running")).scalars().all()
    for job in rows:
        hb = job.heartbeat_at or job.locked_at or job.created_at
        if (now - hb).total_seconds() > job.timeout_s + grace_s:
            count += 1
            if job.attempts >= job.max_attempts:
                job.status = "dead"
                job.finished_at = now
                job.last_error = (job.last_error or "") + " | stalled: worker heartbeat lost"
            else:
                job.status = "queued"
                job.run_at = now
                job.last_error = "recovered after stalled worker"
            job.locked_by = None
    session.commit()
    return count


def release_blocked(session: Session, *, video_id: uuid.UUID | None = None, job_type: str | None = None) -> int:
    q = update(WorkflowJob).where(WorkflowJob.status == "blocked")
    if video_id:
        q = q.where(WorkflowJob.video_id == video_id)
    if job_type:
        q = q.where(WorkflowJob.type == job_type)
    res = session.execute(q.values(status="queued", run_at=now_utc()))
    session.commit()
    return res.rowcount or 0


def cancel(session: Session, job_id: uuid.UUID) -> None:
    session.execute(update(WorkflowJob).where(WorkflowJob.id == job_id, WorkflowJob.status.in_(["queued", "blocked"]))
                    .values(status="cancelled", finished_at=now_utc()))
    session.commit()
