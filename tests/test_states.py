import pytest

from tests import factories as f
from waitwhy.errors import InvalidTransition
from waitwhy.models import AuditLog
from waitwhy.states import S, transition, unblock


def test_happy_path_transitions_are_audited(session):
    v = f.video(session)
    for st in ["RESEARCHING", "RESEARCH_APPROVED", "SCRIPTING", "SCRIPT_APPROVED", "STORYBOARDING", "GENERATING",
               "EDITING", "QUALITY_CHECK", "READY_FOR_REVIEW", "APPROVED", "SCHEDULED", "PUBLISHING", "PUBLISHED",
               "ANALYZING"]:
        transition(session, v, st, "test")
    assert v.state == "ANALYZING"
    assert session.query(AuditLog).filter_by(action="video.transition").count() == 14
    assert "RESEARCHING" in v.stage_timings


def test_cannot_skip_stages(session):
    v = f.video(session)
    with pytest.raises(InvalidTransition):
        transition(session, v, S.PUBLISHED, "test")
    assert v.state == "IDEA"  # failed transition never advances


def test_cannot_jump_from_review_to_published(session):
    v = f.video(session, state="READY_FOR_REVIEW")
    with pytest.raises(InvalidTransition):
        transition(session, v, S.SCHEDULED, "test")


def test_blocked_resumes_only_to_previous_state(session):
    v = f.video(session, state="GENERATING")
    transition(session, v, S.BLOCKED, "test", "budget")
    with pytest.raises(InvalidTransition):
        transition(session, v, S.EDITING, "test")
    unblock(session, v, "test")
    assert v.state == "GENERATING" and v.blocked_reason is None


def test_published_content_never_auto_revised(session):
    v = f.video(session, state="PUBLISHED")
    with pytest.raises(InvalidTransition):
        transition(session, v, S.NEEDS_REVISION, "test")
