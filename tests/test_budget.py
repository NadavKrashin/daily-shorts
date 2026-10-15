from tests import factories as f
from tests.conftest import set_setting
from waitwhy import pipeline
from waitwhy.business import budget
from waitwhy.jobs import queue
from waitwhy.jobs.worker import Worker
from waitwhy.models import Approval, GeneratedAsset, Video, WorkflowJob
from waitwhy.settings import get_config


def _gen_assets(session, kind="scene_video", status="succeeded"):
    return session.query(GeneratedAsset).filter_by(kind=kind, status=status).count()


def test_budget_exhausted_halfway_pauses_without_losing_work(session):
    set_setting(session, "monthly_hard_cap_usd", 1.2)       # mock AI video = $0.50 per 5 s scene
    v = f.video(session, state="GENERATING")
    f.storyboard_with_ai(session, v, n_ai=4)
    queue.enqueue(session, "generate_assets", {"video_id": str(v.id)}, video_id=v.id)
    session.commit()
    w = Worker(worker_id="t", types=["generate_assets"])
    w.run_until_idle()
    session.expire_all()
    v = session.get(Video, v.id)
    assert v.state == "BLOCKED" and v.blocked_reason.startswith("budget")
    assert _gen_assets(session) == 2                             # work done before the cap is kept
    job = session.query(WorkflowJob).filter_by(type="generate_assets").one()
    assert job.status == "blocked" and job.attempts == 0
    ap = session.query(Approval).filter_by(kind="spending", status="pending").one()
    assert ap.payload["scope"] == "monthly"

    # owner approves extra spend -> job resumes and only the missing scenes are generated
    pipeline.decide(session, get_config(session), ap, "approved", "user:test")
    session.commit()
    w.run_until_idle()
    session.expire_all()
    assert _gen_assets(session) == 4
    assert session.query(GeneratedAsset).filter_by(kind="scene_video").count() == 4   # no regeneration
    assert session.get(Video, v.id).state == "GENERATING"   # next stage (metadata) queued, not run here
    assert session.query(WorkflowJob).filter_by(type="generate_assets").one().status == "succeeded"


def test_per_video_ceiling(session):
    set_setting(session, "max_cost_per_video_usd", 0.7)
    v = f.video(session, state="GENERATING", )
    v.budget_usd = None
    f.storyboard_with_ai(session, v, n_ai=3)
    queue.enqueue(session, "generate_assets", {"video_id": str(v.id)}, video_id=v.id)
    session.commit()
    Worker(worker_id="t", types=["generate_assets"]).run_until_idle()
    session.expire_all()
    assert _gen_assets(session) == 1
    assert session.query(Approval).filter_by(kind="spending").one().payload["scope"] == "video"


def test_threshold_alerts_fire_once(session, cfg):
    from waitwhy.models import Notification
    for _ in range(3):
        budget.record_usage(session, cfg, provider="anthropic", model="m", kind="llm", cost_usd=150.0)
    session.commit()
    titles = [n.title for n in session.query(Notification).all()]
    assert sum("50%" in t for t in titles) == 1
    assert sum("80%" in t for t in titles) == 1
    assert sum("95%" in t for t in titles) == 1
    assert not any("EXCEEDED" in t for t in titles)      # $450 < $500 cap
