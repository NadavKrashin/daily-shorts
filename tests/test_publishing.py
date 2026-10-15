import pytest
from datetime import datetime, timezone

from tests import factories as f
from tests.conftest import set_setting
from waitwhy.errors import AuthError, PolicyError, TransientError
from waitwhy.jobs.worker import Worker
from waitwhy.models import Notification, PlatformPost, PublicationJob, Video, WorkflowJob
from waitwhy.publishing import adapters as ad
from waitwhy.publishing import service as pub
from waitwhy.settings import get_config


def _publish_all(session):
    for j in session.query(WorkflowJob).filter_by(type="publish", status="queued").all():
        j.run_at = datetime.now(timezone.utc)
    session.commit()
    Worker(worker_id="t", types=["publish"]).run_until_idle()
    session.expire_all()


def test_independent_platform_statuses(session, cfg):
    """Video OK; Instagram fails; YouTube succeeds; TikTok needs manual action."""
    set_setting(session, "mock_publish_scenario", {"youtube": "ok", "instagram": "fail_permanent",
                                                   "facebook": "ok", "tiktok": "manual"})
    v = f.ready_video(session, cfg)
    pub.schedule_video(session, get_config(session), v, "test")
    session.commit()
    _publish_all(session)
    st = {j.platform: j.status for j in session.query(PublicationJob).all()}
    assert st == {"youtube": "published", "instagram": "failed", "facebook": "published",
                  "tiktok": "manual_action_required"}
    assert session.query(PlatformPost).count() == 2
    assert session.get(Video, v.id).state == "PUBLISHED"
    assert session.query(WorkflowJob).filter_by(type="publish", status="dead").count() == 1


def test_no_public_post_means_not_published(session, cfg):
    set_setting(session, "mock_publish_scenario", {"youtube": "private", "instagram": "fail_permanent",
                                                   "facebook": "fail_permanent", "tiktok": "manual"})
    v = f.ready_video(session, cfg)
    pub.schedule_video(session, get_config(session), v, "test")
    session.commit()
    _publish_all(session)
    v = session.get(Video, v.id)
    assert v.state == "BLOCKED"            # a private upload is never reported as a publication
    assert "youtube=private_uploaded" in v.blocked_reason
    tj = session.query(PublicationJob).filter_by(platform="tiktok").one()
    pub.mark_manually_published(session, tj, "https://www.tiktok.com/@waitwhy/video/1", None, "user:test")
    session.commit()
    assert session.get(Video, v.id).state == "PUBLISHED"


def test_duplicate_publication_is_prevented(session, cfg):
    set_setting(session, "mock_publish_scenario", {"youtube": "ok"})
    v = f.ready_video(session, cfg)
    c = get_config(session)
    pub.schedule_video(session, c, v, "test")
    pub.schedule_video(session, c, v, "test")   # scheduling twice: still one job per platform
    session.commit()
    assert session.query(PublicationJob).filter_by(platform="youtube").count() == 1
    pj = session.query(PublicationJob).filter_by(platform="youtube").one()
    calls = []
    orig = ad.MockAdapter.publish
    ad.MockAdapter.publish = lambda self, req: calls.append(1) or orig(self, req)
    try:
        assert pub.publish(session, c, pj) == "published"
        assert pub.publish(session, c, pj) == "published"   # retry of a finished job is a no-op
    finally:
        ad.MockAdapter.publish = orig
    assert len(calls) == 1
    assert session.query(PlatformPost).filter_by(platform="youtube").count() == 1


def test_interrupted_upload_is_not_blindly_retried(session, cfg):
    v = f.ready_video(session, cfg)
    c = get_config(session)
    pub.schedule_video(session, c, v, "test")
    pj = session.query(PublicationJob).filter_by(platform="youtube").one()
    pj.status = "uploading"                      # worker died mid-upload
    session.commit()
    assert pub.publish(session, c, pj) == "blocked"
    assert any("Verify youtube upload" in n.title for n in session.query(Notification).all())


def test_failed_upload_retries_then_succeeds(session, cfg):
    set_setting(session, "mock_publish_scenario", {"youtube": "fail_transient"})
    v = f.ready_video(session, cfg)
    c = get_config(session)
    pub.schedule_video(session, c, v, "test")
    pj = session.query(PublicationJob).filter_by(platform="youtube").one()
    with pytest.raises(TransientError):
        pub.publish(session, c, pj)
    assert pj.status == "scheduled" and pj.attempts == 1
    set_setting(session, "mock_publish_scenario", {"youtube": "ok"})
    assert pub.publish(session, get_config(session), pj) == "published"


def test_expired_auth_fails_fast_and_alerts(session, cfg):
    set_setting(session, "mock_publish_scenario", {"instagram": "fail_auth"})
    v = f.ready_video(session, cfg)
    c = get_config(session)
    pub.schedule_video(session, c, v, "test")
    pj = session.query(PublicationJob).filter_by(platform="instagram").one()
    with pytest.raises(AuthError):
        pub.publish(session, c, pj)
    assert pj.status == "failed" and pj.error_class == "auth"
    assert any("integration disconnected" in n.title for n in session.query(Notification).all())


def test_youtube_expired_refresh_token(monkeypatch):
    class R:
        status_code, text = 400, '{"error":"invalid_grant"}'
    monkeypatch.setattr(ad.httpx, "post", lambda *a, **k: R())
    with pytest.raises(AuthError, match="expired or revoked"):
        ad.YouTubeAdapter("id", "secret", "refresh", "api")._token()


def test_publication_requires_human_approval(session, cfg):
    v = f.ready_video(session, cfg, approved=False)
    with pytest.raises(PolicyError, match="approval"):
        pub.schedule_video(session, cfg, v, "test")


def test_live_mode_refuses_non_publishable_version(session, cfg):
    set_setting(session, "dry_run_mode", False)
    v = f.ready_video(session, cfg, publishable=False)
    with pytest.raises(PolicyError, match="not publishable"):
        pub.schedule_video(session, get_config(session), v, "test")


def test_tiktok_defaults_to_manual_handoff():
    out = ad.TikTokAdapter("", audited=False, mode="pending_compliance_review").publish(None)
    assert out.status == "manual_action_required" and not out.is_public


def test_supervised_mode_never_auto_approves(session, cfg):
    from waitwhy.pipeline import _auto_approvable
    v = f.ready_video(session, cfg, approved=False)
    c = dict(cfg, operating_mode="supervised", content_approval_required=False, auto_publish_enabled=True)

    class Rv:
        passed, score = True, 100
    assert _auto_approvable(session, c, v, Rv()) is False
    c2 = dict(cfg, operating_mode="controlled", content_approval_required=False, auto_publish_enabled=True)
    assert _auto_approvable(session, c2, v, Rv()) is True
    v.is_sponsored = True
    assert _auto_approvable(session, c2, v, Rv()) is False   # sponsored content always needs a human
