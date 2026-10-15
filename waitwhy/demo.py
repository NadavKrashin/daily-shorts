"""Dry-run of the complete content lifecycle for "Why Traffic Jams Appear Out of Nowhere".

topic -> research/fact-check -> script -> storyboard -> narration -> metadata -> render -> QC ->
(simulated owner approval) -> scheduling -> per-platform publishing via MOCK adapters -> analytics -> report.
Nothing is posted anywhere and no paid API is called.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy import select

from waitwhy import pipeline, reports
from waitwhy.audit import audit
from waitwhy.bootstrap import bootstrap
from waitwhy.db import session_scope
from waitwhy.jobs.worker import Worker
from waitwhy.models import (Approval, PlatformPost, PublicationJob, QualityReview, SystemSetting, Topic, Video,
                            VideoVersion, WorkflowJob)
from waitwhy.providers import registry
from waitwhy.settings import get_config

SLUG = "why-traffic-jams-appear-out-of-nowhere"


def _say(msg: str) -> None:
    print(f"\n=== {msg}")


def run_demo(publish_now: bool = True, workers: int = 3, scenario: dict | None = None) -> dict:
    with session_scope() as s:
        cfg = get_config(s)
        if not cfg.get("dry_run_mode"):
            raise SystemExit("demo refuses to run with dry_run_mode=false")
        print(json.dumps(bootstrap(s)))
        row = s.get(SystemSetting, "mock_publish_scenario")
        sc = scenario or {"youtube": "ok", "instagram": "ok", "facebook": "ok", "tiktok": "manual"}
        if row:
            row.value = sc
        else:
            s.add(SystemSetting(key="mock_publish_scenario", value=sc, updated_by="demo"))
        topic = s.execute(select(Topic).where(Topic.slug == SLUG)).scalar_one()
        video = pipeline.start_production(s, cfg, topic, actor="user:demo")
        vid = video.id
        _say(f"production started for '{topic.title}' (score {topic.score_total}); providers: "
             f"llm={registry.llm(cfg).name}, tts={registry.tts(cfg).name}, visuals={registry.mediagen(cfg).name}")

    w = Worker(worker_id="demo-worker")
    n = w.run_until_idle(100)
    with session_scope() as s:
        v = s.get(Video, vid)
        _say(f"pipeline processed {n} jobs -> video state {v.state}")
        if v.state != "READY_FOR_REVIEW":
            for j in s.execute(select(WorkflowJob).where(WorkflowJob.video_id == vid)).scalars():
                print(f"  job {j.type:18s} {j.status:10s} {j.last_error or ''}")
            return {"state": v.state}
        vv = s.get(VideoVersion, v.current_version_id)
        rv = s.execute(select(QualityReview).where(QualityReview.video_version_id == vv.id)).scalars().first()
        print(f"render v{vv.version}: {vv.duration_s:.1f}s -> {registry.storage(cfg).local_path(vv.storage_key)}")
        print(f"QC passed={rv.passed} score={rv.score} :: {rv.notes}")
        for c in rv.checks:
            flag = "PASS" if c["passed"] else ("WAIVED(dry-run)" if c.get("waived_in_dry_run") else "FAIL")
            print(f"  [{flag:15s}] {c['category']:10s} {c['name']:28s} {c['detail']}")

        _say("simulated owner approval (in production this is the CEO clicking Approve in the dashboard)")
        ap = s.execute(select(Approval).where(Approval.video_id == vid, Approval.kind == "publication",
                                              Approval.status == "pending")).scalars().first()
        pipeline.decide(s, cfg, ap, "approved", "user:demo-owner(simulated)", "dry-run demo approval")

    w.run_until_idle(10)  # schedule_publications
    with session_scope() as s:
        jobs = s.execute(select(PublicationJob).where(PublicationJob.video_id == vid)).scalars().all()
        for pj in jobs:
            print(f"  scheduled {pj.platform:10s} at {pj.scheduled_at.isoformat()} (dry_run={pj.dry_run})")
        if publish_now:
            now = datetime.now(timezone.utc)
            for pj in jobs:
                pj.scheduled_at = now
            for j in s.execute(select(WorkflowJob).where(WorkflowJob.type == "publish", WorkflowJob.video_id == vid,
                                                         WorkflowJob.status == "queued")).scalars():
                j.run_at = now
            audit(s, "user:demo", "publication.demo_publish_now", "video", vid, note="dry-run: slots moved to now")
    w.run_until_idle(20)
    with session_scope() as s:
        v = s.get(Video, vid)
        _say(f"publishing finished -> video state {v.state}")
        for pj in s.execute(select(PublicationJob).where(PublicationJob.video_id == vid)).scalars():
            post = s.execute(select(PlatformPost).where(PlatformPost.publication_job_id == pj.id)).scalar_one_or_none()
            print(f"  {pj.platform:10s} {pj.status:24s} {post.url if post else ''} {pj.last_error or ''}")
        from waitwhy.analytics import ingest
        print("analytics:", ingest.collect(s, cfg), "(mock posts report metrics as UNAVAILABLE - never fabricated)")
        _say("daily CEO report preview")
        f = reports.daily_facts(s, cfg)
        print(reports.render_daily(f, reports.recommendations(f, cfg)))
        return {"state": v.state, "video_id": str(vid)}
