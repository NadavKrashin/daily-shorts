from datetime import datetime, timedelta, timezone

from tests.conftest import set_setting
from waitwhy.db import session_factory
from waitwhy.errors import AuthError, BudgetExceeded, TransientError
from waitwhy.jobs import queue
from waitwhy.jobs.worker import HANDLERS, Worker
from waitwhy.models import Notification, WorkflowJob


def test_enqueue_is_idempotent(session):
    a = queue.enqueue(session, "health_check", {}, idempotency_key="k1")
    b = queue.enqueue(session, "health_check", {}, idempotency_key="k1")
    session.commit()
    assert a.id == b.id
    assert session.query(WorkflowJob).count() == 1


def test_skip_locked_two_workers_never_claim_same_job(session):
    for i in range(3):
        queue.enqueue(session, "research", {"i": i})
    session.commit()
    s1, s2, s3 = session_factory()(), session_factory()(), session_factory()()
    j1 = queue.claim(s1, "w1", ["research"])
    j2 = queue.claim(s2, "w2", ["research"])
    j3 = queue.claim(s3, "w3", ["research"])  # research concurrency limit is 2
    assert j1 and j2 and j1.id != j2.id
    assert j3 is None
    for s in (s1, s2, s3):
        s.close()


def test_transient_failure_retries_with_backoff(session):
    j = queue.enqueue(session, "research", {})
    session.commit()
    claimed = queue.claim(session, "w", ["research"])
    status = queue.fail(session, claimed, TransientError("503"))
    assert status == "queued" and claimed.run_at > datetime.now(timezone.utc)
    assert claimed.attempts == 1


def test_permanent_auth_error_goes_dead_with_high_alert(session):
    queue.enqueue(session, "publish", {})
    session.commit()
    j = queue.claim(session, "w", ["publish"])
    assert queue.fail(session, j, AuthError("token expired")) == "dead"
    n = session.query(Notification).one()
    assert n.severity == "high"


def test_retries_exhausted_go_dead(session):
    queue.enqueue(session, "script", {}, max_attempts=2)
    session.commit()
    for _ in range(2):
        j = queue.claim(session, "w", ["script"])
        j.run_at = datetime.now(timezone.utc)
        session.commit()
        st = queue.fail(session, j, TransientError("x"))
        j.run_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        session.commit()
    assert st == "dead"


def test_budget_block_parks_without_consuming_attempt(session):
    queue.enqueue(session, "generate_assets", {})
    session.commit()
    j = queue.claim(session, "w", ["generate_assets"])
    assert queue.fail(session, j, BudgetExceeded("cap")) == "blocked"
    assert j.attempts == 0
    assert queue.release_blocked(session) == 1


def test_stalled_job_is_recovered(session):
    queue.enqueue(session, "edit", {})
    session.commit()
    j = queue.claim(session, "w", ["edit"])
    j.heartbeat_at = datetime.now(timezone.utc) - timedelta(hours=3)
    session.commit()
    assert queue.recover_stalled(session) == 1
    session.refresh(j)
    assert j.status == "queued"


def test_paused_automation_only_runs_essential_jobs(session):
    set_setting(session, "automation_paused", True)
    queue.enqueue(session, "research", {})
    queue.enqueue(session, "health_check", {})
    session.commit()
    j = queue.claim(session, "w")
    assert j.type == "health_check"
    assert queue.claim(session, "w") is None


def test_pause_all_publishing_blocks_publish_jobs(session):
    set_setting(session, "publishing_paused", True)
    queue.enqueue(session, "publish", {})
    session.commit()
    assert queue.claim(session, "w") is None


def test_worker_executes_and_records_result(session, monkeypatch):
    monkeypatch.setitem(HANDLERS, "content_planning", lambda s, j: {"ok": True})
    queue.enqueue(session, "content_planning", {})
    session.commit()
    w = Worker(worker_id="t", types=["content_planning"])
    assert w.run_until_idle() == 1
    j = session.query(WorkflowJob).one()
    session.refresh(j)
    assert j.status == "succeeded" and j.result == {"ok": True}
