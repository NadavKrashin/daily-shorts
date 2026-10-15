"""End-to-end dry run with mock providers for a topic WITHOUT curated content: the pipeline runs, renders a
valid video, and QC marks it not publishable (mock research) - proving mock output can never go live."""
import os

import pytest

from tests import factories as f
from waitwhy import pipeline
from waitwhy.jobs.worker import Worker
from waitwhy.models import QualityReview, Video, VideoVersion

pytestmark = pytest.mark.skipif(os.environ.get("SKIP_SLOW") == "1", reason="slow: renders a full video")


def test_full_pipeline_with_mock_providers(session, cfg):
    t = f.topic(session, title="Why Bridges Have Gaps")
    v = pipeline.start_production(session, cfg, t, actor="test")
    session.commit()
    Worker(worker_id="e2e").run_until_idle(50)
    session.expire_all()
    v = session.get(Video, v.id)
    assert v.state == "READY_FOR_REVIEW", v.blocked_reason
    vv = session.get(VideoVersion, v.current_version_id)
    rv = session.query(QualityReview).filter_by(video_version_id=vv.id).one()
    assert rv.passed and vv.manifest["publishable"] is False
    names = {c["name"] for c in rv.checks if c.get("waived_in_dry_run")}
    assert {"no_mock_content", "rights_cleared"} <= names
    tech = {c["name"]: c["passed"] for c in rv.checks if c["category"] == "technical"}
    assert all(tech.values()), tech
