"""Explicit content workflow state machine.

A failed transition raises ``InvalidTransition`` - the pipeline never silently advances.
"""
from __future__ import annotations

import enum
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from waitwhy.audit import audit
from waitwhy.errors import InvalidTransition
from waitwhy.models import Video


class S(str, enum.Enum):
    IDEA = "IDEA"
    RESEARCHING = "RESEARCHING"
    RESEARCH_APPROVED = "RESEARCH_APPROVED"
    SCRIPTING = "SCRIPTING"
    SCRIPT_APPROVED = "SCRIPT_APPROVED"
    STORYBOARDING = "STORYBOARDING"
    GENERATING = "GENERATING"
    EDITING = "EDITING"
    QUALITY_CHECK = "QUALITY_CHECK"
    READY_FOR_REVIEW = "READY_FOR_REVIEW"
    APPROVED = "APPROVED"
    SCHEDULED = "SCHEDULED"
    PUBLISHING = "PUBLISHING"
    PUBLISHED = "PUBLISHED"
    ANALYZING = "ANALYZING"
    NEEDS_REVISION = "NEEDS_REVISION"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


_SIDE = {S.NEEDS_REVISION, S.BLOCKED, S.FAILED, S.CANCELLED}

TRANSITIONS: dict[S, set[S]] = {
    S.IDEA: {S.RESEARCHING},
    S.RESEARCHING: {S.RESEARCH_APPROVED},
    S.RESEARCH_APPROVED: {S.SCRIPTING},
    S.SCRIPTING: {S.SCRIPT_APPROVED},
    S.SCRIPT_APPROVED: {S.STORYBOARDING},
    S.STORYBOARDING: {S.GENERATING},
    S.GENERATING: {S.EDITING},
    S.EDITING: {S.QUALITY_CHECK},
    S.QUALITY_CHECK: {S.READY_FOR_REVIEW, S.APPROVED},   # APPROVED only via auto-approval policy
    S.READY_FOR_REVIEW: {S.APPROVED},
    S.APPROVED: {S.SCHEDULED},
    S.SCHEDULED: {S.PUBLISHING, S.APPROVED},              # APPROVED = rescheduling
    S.PUBLISHING: {S.PUBLISHED},
    S.PUBLISHED: {S.ANALYZING},
    S.ANALYZING: set(),
    # Repair loop: a revision re-enters the pipeline at the earliest affected stage.
    S.NEEDS_REVISION: {S.RESEARCHING, S.SCRIPTING, S.STORYBOARDING, S.GENERATING, S.EDITING},
    S.BLOCKED: set(),      # resumes to state_before_block (see unblock)
    S.FAILED: {S.RESEARCHING, S.SCRIPTING, S.STORYBOARDING, S.GENERATING, S.EDITING, S.QUALITY_CHECK},
    S.CANCELLED: set(),
}
# Every active state may move to a side state.
for _s in list(TRANSITIONS):
    if _s not in {S.CANCELLED, S.ANALYZING}:
        TRANSITIONS[_s] |= _SIDE - {_s}
TRANSITIONS[S.PUBLISHED] -= {S.NEEDS_REVISION}   # never "revise" live content automatically

KANBAN_COLUMNS = [
    ("Ideas", [S.IDEA]),
    ("Researching", [S.RESEARCHING, S.RESEARCH_APPROVED]),
    ("Scriptwriting", [S.SCRIPTING, S.SCRIPT_APPROVED]),
    ("Storyboarding", [S.STORYBOARDING]),
    ("Generating", [S.GENERATING]),
    ("Editing", [S.EDITING]),
    ("Quality Review", [S.QUALITY_CHECK, S.NEEDS_REVISION]),
    ("Awaiting Approval", [S.READY_FOR_REVIEW, S.BLOCKED]),
    ("Scheduled", [S.APPROVED, S.SCHEDULED, S.PUBLISHING]),
    ("Published", [S.PUBLISHED, S.ANALYZING]),
    ("Failed", [S.FAILED, S.CANCELLED]),
]


def can_transition(src: str, dst: str) -> bool:
    return S(dst) in TRANSITIONS.get(S(src), set())


def transition(session: Session, video: Video, dst: S | str, actor: str, reason: str = "") -> Video:
    dst = S(dst)
    src = S(video.state)
    if src == dst:
        return video
    if src == S.BLOCKED:
        allowed = dst in _SIDE or (video.state_before_block and dst == S(video.state_before_block))
        if not allowed:
            raise InvalidTransition(f"BLOCKED video can only resume to {video.state_before_block}, not {dst}")
    elif not can_transition(src, dst):
        raise InvalidTransition(f"{src.value} -> {dst.value} is not an allowed transition")
    if dst == S.BLOCKED:
        video.state_before_block = src.value
        video.blocked_reason = reason
    elif src == S.BLOCKED:
        video.blocked_reason = None
    now = datetime.now(timezone.utc)
    # Stage timing (time spent in the state being left)
    if video.state_changed_at:
        spent = (now - video.state_changed_at).total_seconds()
        timings = dict(video.stage_timings or {})
        timings[src.value] = round(timings.get(src.value, 0) + spent, 1)
        video.stage_timings = timings
    video.state = dst.value
    video.state_changed_at = now
    audit(session, actor, "video.transition", "video", video.id, before={"state": src.value},
          after={"state": dst.value}, reason=reason)
    return video


def unblock(session: Session, video: Video, actor: str, reason: str = "") -> Video:
    if video.state != S.BLOCKED.value or not video.state_before_block:
        raise InvalidTransition("video is not blocked")
    return transition(session, video, S(video.state_before_block), actor, reason or "unblocked")
