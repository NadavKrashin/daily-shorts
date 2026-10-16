"""Deterministic pipeline orchestration: each stage = (transition in) -> agent work -> (transition out) ->
enqueue next stage. Agents never move state themselves; this module owns every transition."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from waitwhy.agents import editor, metadata, production, qc, research, writer
from waitwhy.agents.base import record_decision
from waitwhy.audit import audit
from waitwhy.errors import ApprovalRequired, BudgetExceeded, InvalidTransition, PolicyError, QualityGateFailed
from waitwhy.jobs import queue
from waitwhy.models import Approval, Topic, Video, VideoVersion
from waitwhy.notify import alert
from waitwhy.publishing import service as pub
from waitwhy.states import S, transition, unblock

AGENT = "agent:coo"


def start_production(session: Session, cfg: dict, topic: Topic, actor: str = AGENT, priority: int = 0) -> Video:
    existing = session.execute(select(Video).where(Video.topic_id == topic.id,
                                                   Video.state.notin_([S.CANCELLED.value]))).scalars().first()
    if existing:
        return existing
    video = Video(topic_id=topic.id, title=topic.title, slug=topic.slug, category=topic.category, state=S.IDEA.value,
                  state_changed_at=datetime.now(timezone.utc), requires_human_review=topic.requires_human_review,
                  priority=priority, budget_usd=cfg["max_cost_per_video_usd"])
    session.add(video)
    session.flush()
    topic.status = "in_production"
    audit(session, actor, "video.created", "video", video.id, topic=topic.title)
    transition(session, video, S.RESEARCHING, actor, "production started")
    queue.enqueue(session, "research", {"video_id": str(video.id)}, video_id=video.id,
                  idempotency_key=f"research:{video.id}:1")
    return video


def _next(session, job_type: str, video: Video, tag: str = "1") -> None:
    queue.enqueue(session, job_type, {"video_id": str(video.id)}, video_id=video.id,
                  idempotency_key=f"{job_type}:{video.id}:{tag}:{datetime.now(timezone.utc).timestamp():.0f}")


def _enter(session, video: Video, state: S, actor: str) -> None:
    if video.state != state.value:
        transition(session, video, state, actor)


def stage_research(session: Session, cfg: dict, video: Video, job_id=None) -> dict:
    _enter(session, video, S.RESEARCHING, AGENT)
    fc = research.run(session, cfg, video, job_id)
    if fc.status == "verified":
        transition(session, video, S.RESEARCH_APPROVED, "agent:factcheck", f"fact sheet v{fc.version} verified")
        _next(session, "script", video)
    elif fc.status == "needs_human":
        session.add(Approval(video_id=video.id, kind="research", status="pending", target_type="fact_check",
                             target_id=str(fc.id), reason="High-risk topic: a human must review the fact sheet",
                             payload={"fact_check_id": str(fc.id)}))
        transition(session, video, S.BLOCKED, "agent:factcheck", "awaiting human review of high-risk research")
    elif fc.status == "rejected":
        transition(session, video, S.CANCELLED, "agent:factcheck", "premise could not be supported")
        video.topic.status = "rejected"
    else:
        transition(session, video, S.NEEDS_REVISION, "agent:factcheck",
                   "research incomplete: " + "; ".join(fc.fact_sheet.get("validation_issues", [])[:3]))
    return {"fact_check": fc.status}


def stage_script(session: Session, cfg: dict, video: Video, job_id=None) -> dict:
    _enter(session, video, S.SCRIPTING, AGENT)
    script = writer.write_script(session, cfg, video, job_id)
    if cfg.get("script_approval_required"):
        session.add(Approval(video_id=video.id, kind="script", status="pending", target_type="script",
                             target_id=str(script.id), reason="Script approval is enabled in settings"))
        transition(session, video, S.BLOCKED, "agent:scriptwriter", "awaiting script approval")
        return {"script": "awaiting_approval"}
    transition(session, video, S.SCRIPT_APPROVED, "agent:scriptwriter", f"script v{script.version} passed checks")
    _next(session, "storyboard", video)
    return {"words": script.word_count}


def stage_storyboard(session: Session, cfg: dict, video: Video, job_id=None) -> dict:
    _enter(session, video, S.STORYBOARDING, AGENT)
    board = writer.make_storyboard(session, cfg, video, job_id)
    transition(session, video, S.GENERATING, "agent:storyboard", f"storyboard v{board.version} approved")
    _next(session, "generate_assets", video)
    return {"scenes": len(board.scenes)}


def stage_generate(session: Session, cfg: dict, video: Video, job_id=None) -> dict:
    _enter(session, video, S.GENERATING, AGENT)
    stats = production.generate_assets(session, cfg, video, job_id)
    _next(session, "prepare_metadata", video)
    return stats


def stage_metadata(session: Session, cfg: dict, video: Video, job_id=None) -> dict:
    metadata.prepare(session, cfg, video, job_id)
    transition(session, video, S.EDITING, "agent:metadata", "assets + metadata ready")
    _next(session, "edit", video)
    return {"title": video.publish_metadata.get("youtube_title")}


def stage_edit(session: Session, cfg: dict, video: Video, job_id=None) -> dict:
    _enter(session, video, S.EDITING, AGENT)
    vv = editor.render(session, cfg, video, job_id)
    transition(session, video, S.QUALITY_CHECK, "agent:editor", f"rendered v{vv.version} ({vv.duration_s:.1f}s)")
    _next(session, "qc", video)
    return {"version": vv.version, "duration_s": vv.duration_s}


def stage_qc(session: Session, cfg: dict, video: Video, job_id=None) -> dict:
    _enter(session, video, S.QUALITY_CHECK, AGENT)
    review = qc.run(session, cfg, video, job_id)
    return after_qc(session, cfg, video, review)


def after_qc(session: Session, cfg: dict, video: Video, review, actor: str = "agent:qc") -> dict:
    """Act on a QC review: failed -> NEEDS_REVISION; passed -> auto-approve and schedule (autonomous
    mode) or ask the owner. Shared by the in-app pipeline and imported episodes."""
    if not review.passed:
        transition(session, video, S.NEEDS_REVISION, actor, "; ".join(review.blocking_issues)[:900])
        vv = session.get(VideoVersion, video.current_version_id)
        if (vv.manifest or {}).get("source") == "claude_higgsfield_run":
            # Nothing in the app can repair an episode made by the production runs, so tell the owner now.
            alert(session, "high", "quality", f"Episode held, not posted: {video.title}",
                  "It failed the app's check:\n- " + "\n- ".join(review.blocking_issues)
                  + "\n\nThe next production run fixes held episodes first; ask the production session to "
                  "fix it now if it should go out sooner.", dedupe_key=f"qc:{video.id}:{review.id}", video_id=video.id)
        else:
            alert(session, "low", "quality", f"QC failed: {video.title}", "\n".join(review.blocking_issues),
                  dedupe_key=f"qc:{video.id}:{review.id}", video_id=video.id)
        return {"passed": False, "blocking": review.blocking_issues}
    if _auto_approvable(session, cfg, video, review):
        session.add(Approval(video_id=video.id, kind="publication", status="approved", decided_by="policy:auto",
                             decided_at=datetime.now(timezone.utc), reason=f"auto-approved in {cfg['operating_mode']} mode",
                             target_type="video_version", target_id=str(video.current_version_id)))
        transition(session, video, S.APPROVED, "policy:auto", "passed all gates; auto-publish enabled")
        _next(session, "schedule_publications", video)
    else:
        session.add(Approval(video_id=video.id, kind="publication", status="pending", target_type="video_version",
                             target_id=str(video.current_version_id),
                             reason=f"QC passed (score {review.score}). {review.notes}"))
        transition(session, video, S.READY_FOR_REVIEW, actor, "awaiting human approval")
    return {"passed": True, "score": review.score, "notes": review.notes}


def _auto_approvable(session, cfg, video: Video, review) -> bool:
    if cfg.get("operating_mode") == "supervised" or cfg.get("content_approval_required") \
            or not cfg.get("auto_publish_enabled"):
        return False
    vv = session.get(VideoVersion, video.current_version_id)
    if not vv.manifest.get("publishable") or video.requires_human_review or video.is_sponsored:
        return False
    return review.passed and (review.score or 0) >= 90


# ------------------------------------------------------------------ human decisions
def decide(session: Session, cfg: dict, approval: Approval, decision: str, actor: str, notes: str = "") -> None:
    if approval.status != "pending":
        raise PolicyError(f"approval already {approval.status}")
    if decision not in ("approved", "rejected", "changes_requested"):
        raise ValueError(decision)
    approval.status, approval.decided_by = decision, actor
    approval.decided_at, approval.decision_notes = datetime.now(timezone.utc), notes
    audit(session, actor, f"approval.{decision}", "approval", approval.id, kind=approval.kind, notes=notes)
    video = session.get(Video, approval.video_id) if approval.video_id else None
    if approval.kind == "publication" and video:
        if decision == "approved":
            transition(session, video, S.APPROVED, actor, notes or "approved for publication")
            _next(session, "schedule_publications", video)
        elif decision == "changes_requested":
            transition(session, video, S.NEEDS_REVISION, actor, notes or "changes requested")
        else:
            transition(session, video, S.CANCELLED, actor, notes or "rejected by owner")
    elif approval.kind in ("research", "script") and video:
        if decision == "approved":
            target = S.RESEARCH_APPROVED if approval.kind == "research" else S.SCRIPT_APPROVED
            if approval.kind == "research":
                from waitwhy.models import FactCheck
                fc = session.get(FactCheck, uuid.UUID(approval.target_id))
                fc.status = "verified"
            if video.state == S.BLOCKED.value:
                video.state_before_block = target.value
                unblock(session, video, actor, f"{approval.kind} approved")
            _next(session, "script" if approval.kind == "research" else "storyboard", video)
        else:
            transition(session, video, S.CANCELLED if decision == "rejected" else S.NEEDS_REVISION, actor, notes)
    elif approval.kind == "spending":
        if decision == "approved":
            # resume everything that was parked by the budget guard
            n = queue.release_blocked(session, video_id=video.id if video else None)
            for v in session.execute(select(Video).where(Video.state == S.BLOCKED.value)).scalars():
                if (v.blocked_reason or "").startswith("budget"):
                    unblock(session, v, actor, "spending approved")
            record_decision(session, "coo", "spending", f"spending approved by {actor}; {n} jobs resumed")


def request_revision(session: Session, cfg: dict, video: Video, from_stage: str, actor: str, notes: str = "") -> None:
    """Re-enter the pipeline at the earliest affected stage (targeted repair, not a full redo)."""
    stage_map = {"research": (S.RESEARCHING, "research"), "script": (S.SCRIPTING, "script"),
                 "storyboard": (S.STORYBOARDING, "storyboard"), "generate": (S.GENERATING, "generate_assets"),
                 "edit": (S.EDITING, "edit")}
    state, job = stage_map[from_stage]
    if video.state not in (S.NEEDS_REVISION.value, S.FAILED.value):
        transition(session, video, S.NEEDS_REVISION, actor, notes or "revision requested")
    transition(session, video, state, actor, f"revision from {from_stage}: {notes}")
    _next(session, job, video, tag=f"rev{datetime.now(timezone.utc).timestamp():.0f}")


def on_stage_error(session: Session, video: Video, exc: BaseException, stage: str) -> None:
    """Map stage exceptions to visible video states (never silently stuck)."""
    try:
        if isinstance(exc, BudgetExceeded):
            if video.state != S.BLOCKED.value:
                transition(session, video, S.BLOCKED, "agent:budget", f"budget: {exc}")
        elif isinstance(exc, ApprovalRequired):
            if video.state != S.BLOCKED.value:
                transition(session, video, S.BLOCKED, "agent:coo", f"approval: {exc}")
        elif isinstance(exc, (QualityGateFailed,)):
            transition(session, video, S.NEEDS_REVISION, f"agent:{stage}", str(exc)[:900])
    except InvalidTransition:
        pass
