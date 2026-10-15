"""Agent A - Chief Operating Officer: health, inventory, prioritisation, recovery, escalation.

Rules-first (deterministic) so it never invents metrics; the LLM is only used to phrase reports.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from waitwhy.agents.base import record_decision
from waitwhy.business import budget
from waitwhy.jobs import queue
from waitwhy.models import PublicationJob, SystemSetting, Topic, Video, WorkflowJob
from waitwhy.notify import alert
from waitwhy.providers import registry
from waitwhy.settings import secrets
from waitwhy.states import S

WORK_STATES = {S.RESEARCHING: "research", S.RESEARCH_APPROVED: "script", S.SCRIPTING: "script",
               S.SCRIPT_APPROVED: "storyboard", S.STORYBOARDING: "storyboard", S.GENERATING: "generate_assets",
               S.EDITING: "edit", S.QUALITY_CHECK: "qc", S.APPROVED: "schedule_publications"}
IN_FLIGHT = [s.value for s in WORK_STATES] + [S.IDEA.value]


def _now():
    return datetime.now(timezone.utc)


def _setting(session: Session, key: str, value) -> None:
    row = session.get(SystemSetting, key)
    if row:
        row.value = value
    else:
        session.add(SystemSetting(key=key, value=value, updated_by="agent:coo"))


def credential_status() -> dict:
    s = secrets()
    return {
        "anthropic": bool(s.anthropic_api_key), "elevenlabs": bool(s.elevenlabs_api_key and s.elevenlabs_voice_id),
        "higgsfield": bool(s.higgsfield_api_key and s.higgsfield_api_secret), "heygen": bool(s.heygen_api_key),
        "youtube": bool(s.youtube_client_id and s.youtube_refresh_token),
        "instagram": bool(s.instagram_user_id and s.instagram_access_token),
        "facebook": bool(s.meta_page_id and s.meta_page_access_token),
        "tiktok_direct_post": bool(s.tiktok_access_token and s.tiktok_app_audited),
        "s3_storage": bool(s.s3_bucket), "email": bool(s.smtp_host), "telegram": bool(s.telegram_bot_token),
        "dev_voice_piper": bool(s.piper_voice_path),
    }


def inventory(session: Session) -> dict:
    count = lambda q: session.execute(q).scalar() or 0  # noqa: E731
    by_state = dict(session.execute(select(Video.state, func.count()).group_by(Video.state)).all())
    return {
        "candidate_topics": count(select(func.count()).select_from(Topic).where(Topic.status == "evaluated")),
        "researched_topics": sum(by_state.get(s, 0) for s in ("RESEARCH_APPROVED", "SCRIPTING", "SCRIPT_APPROVED",
                                                              "STORYBOARDING", "GENERATING", "EDITING", "QUALITY_CHECK")),
        "production_ready": sum(by_state.get(s, 0) for s in ("SCRIPT_APPROVED", "STORYBOARDING", "GENERATING",
                                                             "EDITING", "QUALITY_CHECK")),
        "finished_videos": sum(by_state.get(s, 0) for s in ("READY_FOR_REVIEW", "APPROVED", "SCHEDULED")),
        "in_flight": sum(by_state.get(s, 0) for s in IN_FLIGHT),
        "by_state": by_state,
    }


def health_check(session: Session, cfg: dict) -> dict:
    now = _now()
    problems, fixed = [], []
    # scheduler heartbeat
    hb = session.get(SystemSetting, "scheduler_heartbeat")
    sched_age = (now - datetime.fromisoformat(hb.value)).total_seconds() if hb and hb.value else None
    if sched_age is None or sched_age > 300:
        problems.append(("high", "Scheduler heartbeat missing/stale", f"age={sched_age}"))
    # workers: any worker heartbeat in the last 5 minutes
    workers = [r for r in session.execute(select(SystemSetting).where(SystemSetting.key.like("worker_heartbeat:%"))).scalars()
               if r.value and (now - datetime.fromisoformat(r.value)).total_seconds() < 300]
    if not workers:
        problems.append(("high", "No live workers", "no worker heartbeat in 5 minutes"))
    # storage
    try:
        registry.storage(cfg).health()
        storage_ok = True
    except Exception as e:  # noqa: BLE001
        storage_ok = False
        problems.append(("high", "Object storage unavailable", str(e)))
    # jobs
    recovered = queue.recover_stalled(session)
    if recovered:
        fixed.append(f"re-queued {recovered} stalled jobs")
    dead = session.execute(select(WorkflowJob).where(WorkflowJob.status == "dead",
                                                     WorkflowJob.finished_at > now - timedelta(hours=24))).scalars().all()
    for j in dead:  # bounded auto-retry of transient-looking failures (once)
        if j.error_class in ("transient", "unexpected") and not (j.payload or {}).get("_auto_retried"):
            j.status, j.run_at, j.attempts = "queued", now, max(0, j.max_attempts - 1)
            j.payload = {**(j.payload or {}), "_auto_retried": True}
            fixed.append(f"auto-retried dead job {j.type}")
    blocked = session.execute(select(func.count()).select_from(WorkflowJob).where(WorkflowJob.status == "blocked")).scalar()
    creds = credential_status()
    for p in cfg["platforms"]:
        if cfg["platforms"][p].get("enabled") and not cfg.get("dry_run_mode"):
            key = {"tiktok": "tiktok_direct_post"}.get(p, p)
            if not creds.get(key) and not (p == "tiktok"):
                problems.append(("high", f"{p} integration not connected", "publishing will fail until connected"))
    st = budget.status(session, cfg)
    today_end = now + timedelta(hours=24)
    scheduled = session.execute(select(PublicationJob).where(PublicationJob.status == "scheduled",
                                                             PublicationJob.scheduled_at < today_end)).scalars().all()
    inv = inventory(session)
    result = {"checked_at": now.isoformat(), "scheduler_age_s": sched_age, "live_workers": len(workers),
              "storage_ok": storage_ok, "db_ok": True, "dead_jobs_24h": len(dead), "blocked_jobs": blocked,
              "credentials": creds, "budget": st, "publications_next_24h": len(scheduled), "inventory": inv,
              "auto_fixes": fixed, "problems": [p[1] for p in problems]}
    for sev, title, body in problems:
        alert(session, sev, "health", title, body, dedupe_key=f"health:{title}")
    _setting(session, "last_health", result)
    record_decision(session, "coo", "health_check",
                    f"{len(problems)} problems, {len(fixed)} auto-fixes, {len(workers)} workers", output=result)
    return result


def content_planning(session: Session, cfg: dict) -> dict:
    from waitwhy.agents import trends
    from waitwhy.pipeline import start_production

    inv = inventory(session)
    tgt = cfg["inventory_targets"]
    actions = []
    if inv["candidate_topics"] < tgt["candidate_topics"]:
        if inv["candidate_topics"] == 0:
            n = trends.seed_backlog(session, cfg)
            actions.append(f"seeded {n} backlog topics")
        queue.enqueue(session, "trend_discovery", {"count": min(15, tgt["candidate_topics"] - inv["candidate_topics"] + 5)},
                      idempotency_key=f"trends:{_now().date().isoformat()}")
        actions.append("queued trend discovery")
    st = budget.status(session, cfg)
    weekly = cfg.get("weekly_video_target", 5)
    want = max(0, min(2, tgt["finished_videos"] + tgt["production_ready"] - inv["finished_videos"] - inv["in_flight"]))
    paused = session.get(SystemSetting, "automation_paused")
    if paused and paused.value:
        want, actions = 0, actions + ["automation paused - no new production"]
    elif st["remaining_vs_cap_usd"] < cfg["target_cost_per_video_usd"]:
        want = 0
        actions.append("budget too low to start new videos")
        alert(session, "high", "budget", "Production paused: monthly budget nearly exhausted",
              f"Remaining under cap: ${st['remaining_vs_cap_usd']:.2f}", dedupe_key=f"plan-budget:{st['month']}")
    started = []
    for topic in trends.choose_next(session, cfg, want):
        v = start_production(session, cfg, topic)
        started.append(v.title)
    if started:
        actions.append(f"started production: {started}")
    if inv["candidate_topics"] < 10:
        alert(session, "low", "inventory", "Topic backlog running low", f"{inv['candidate_topics']} evaluated topics",
              dedupe_key="backlog-low")
    record_decision(session, "coo", "content_planning", "; ".join(actions) or "inventory healthy - no action",
                    output={"inventory": inv, "weekly_target": weekly})
    return {"inventory": inv, "actions": actions}


def production_tick(session: Session, cfg: dict) -> dict:
    """Recovery: any in-flight video with no live job gets its stage job re-enqueued."""
    requeued = []
    active_status = ["queued", "running", "blocked"]
    for v in session.execute(select(Video).where(Video.state.in_([s.value for s in WORK_STATES]))).scalars():
        has_job = session.execute(select(WorkflowJob.id).where(WorkflowJob.video_id == v.id,
                                                               WorkflowJob.status.in_(active_status))).first()
        if has_job:
            continue
        stale = v.state_changed_at and (_now() - v.state_changed_at) > timedelta(minutes=30)
        if stale:
            job = WORK_STATES[S(v.state)]
            queue.enqueue(session, job, {"video_id": str(v.id)}, video_id=v.id,
                          idempotency_key=f"{job}:{v.id}:recover:{_now().strftime('%Y%m%d%H')}")
            requeued.append(f"{v.title}:{job}")
    if requeued:
        record_decision(session, "coo", "production_tick", f"re-enqueued orphaned stages: {requeued}")
    return {"requeued": requeued}


def publish_due(session: Session, cfg: dict) -> dict:
    now = _now()
    missed = []
    for pj in session.execute(select(PublicationJob).where(PublicationJob.status == "scheduled",
                                                           PublicationJob.scheduled_at < now - timedelta(minutes=30))).scalars():
        has = session.execute(select(WorkflowJob.id).where(WorkflowJob.type == "publish",
                                                           WorkflowJob.status.in_(["queued", "running"]),
                                                           WorkflowJob.payload["publication_job_id"].astext == str(pj.id))).first()
        if not has:
            queue.enqueue(session, "publish", {"publication_job_id": str(pj.id)}, video_id=pj.video_id,
                          idempotency_key=f"publish:{pj.id}:missed:{now.strftime('%Y%m%d%H')}")
            missed.append(pj.platform)
            alert(session, "high", "publishing", f"Missed publishing window on {pj.platform}",
                  f"publication job {pj.id} was due {pj.scheduled_at}", dedupe_key=f"missed:{pj.id}")
    stuck = session.execute(select(PublicationJob).where(PublicationJob.status == "processing",
                                                         PublicationJob.updated_at < now - timedelta(hours=2))).scalars().all()
    for pj in stuck:
        alert(session, "high", "publishing", f"{pj.platform} upload still processing after 2h",
              f"publication job {pj.id} - verify on the platform", dedupe_key=f"processing:{pj.id}")
    return {"missed_requeued": missed, "stuck_processing": len(stuck)}
