"""Command line entry point: ``waitwhy <command>``."""
from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from datetime import datetime, timezone

from sqlalchemy import select


class _RedactSecrets(logging.Filter):
    """Platform APIs (Instagram, Facebook) take the access token as a URL parameter, and httpx logs every
    request URL at INFO, so tokens ended up in the log files. Mask them in every log line."""
    PATTERN = re.compile(r"((?:access_token|client_secret|refresh_token|fb_exchange_token|code)=)[^&\s\"']+")

    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        clean = self.PATTERN.sub(r"\1[redacted]", msg)
        if clean != msg:
            record.msg, record.args = clean, None
        return True


def _setup_logging(level: str = "INFO") -> None:
    logging.basicConfig(level=getattr(logging, level), format='{"t":"%(asctime)s","lvl":"%(levelname)s",'
                        '"logger":"%(name)s","msg":"%(message)s"}')
    for h in logging.getLogger().handlers:
        h.addFilter(_RedactSecrets())
    for noisy in ("httpx", "httpcore"):   # one INFO line per API call, each with the full URL
        logging.getLogger(noisy).setLevel(logging.WARNING)


def cmd_migrate(_):
    from alembic import command
    from alembic.config import Config

    from waitwhy.settings import ROOT
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "migrations"))
    command.upgrade(cfg, "head")
    print("database migrated")


def cmd_init(_):
    from waitwhy.bootstrap import bootstrap
    from waitwhy.db import session_scope
    with session_scope() as s:
        print(json.dumps(bootstrap(s), indent=1))


def cmd_worker(a):
    from waitwhy.jobs.worker import Worker
    Worker(types=a.types.split(",") if a.types else None).run_forever()


def cmd_scheduler(_):
    from waitwhy.jobs import scheduler
    scheduler.run_forever()


def cmd_api(a):
    import uvicorn
    uvicorn.run("waitwhy.api.app:app", host=a.host, port=a.port, proxy_headers=True)


def cmd_produce(a):
    from waitwhy import pipeline
    from waitwhy.agents.trends import add_candidate, slugify
    from waitwhy.db import session_scope
    from waitwhy.models import Topic
    from waitwhy.schemas import TopicCandidate, TopicScores
    from waitwhy.settings import get_config
    with session_scope() as s:
        cfg = get_config(s)
        t = s.execute(select(Topic).where(Topic.slug == slugify(a.topic))).scalar_one_or_none()
        if t is None:
            t = add_candidate(s, cfg, TopicCandidate(
                title=a.topic, category=a.category, angle=a.angle or a.topic, summary=a.topic, keywords=[],
                risk_flags=[], scores=TopicScores(**{k: 70 for k in TopicScores.model_fields}),
                reasoning="owner-submitted topic"), origin="owner")
        v = pipeline.start_production(s, cfg, t, actor="user:cli")
        print(f"production started: video {v.id} ({v.slug}) state={v.state}")


def cmd_run(a):
    from waitwhy.jobs.worker import Worker
    n = Worker().run_until_idle(a.max_jobs)
    print(f"processed {n} jobs")


def cmd_approve(a):
    from waitwhy import pipeline
    from waitwhy.db import session_scope
    from waitwhy.models import Approval, Video
    from waitwhy.settings import get_config
    with session_scope() as s:
        v = s.execute(select(Video).where(Video.slug == a.slug)).scalar_one()
        ap = s.execute(select(Approval).where(Approval.video_id == v.id, Approval.status == "pending",
                                              Approval.kind == a.kind)).scalars().first()
        if not ap:
            sys.exit(f"no pending {a.kind} approval for {a.slug}")
        pipeline.decide(s, get_config(s), ap, a.decision, f"user:{a.user}", a.notes)
        print(f"{a.kind} approval -> {a.decision}; video state {v.state}")


def cmd_report(a):
    from waitwhy import reports
    from waitwhy.db import session_scope
    from waitwhy.settings import get_config
    with session_scope() as s:
        cfg = get_config(s)
        f = reports.daily_facts(s, cfg)
        print(reports.render_daily(f, reports.recommendations(f, cfg)))


def cmd_import(a):
    from pathlib import Path

    from waitwhy import importer
    from waitwhy.db import session_scope
    from waitwhy.settings import get_config
    with session_scope() as s:
        cfg = get_config(s)
        if a.pull:
            print(importer.git_pull())
        for slug, result in importer.import_all(s, cfg, Path(a.file) if a.file else None).items():
            print(f"{slug}: {result}")


def cmd_tick(_):
    from waitwhy.jobs import scheduler
    print("\n".join(scheduler.tick()))


def cmd_backup(_):
    from waitwhy.ops.backup import run_backup
    print(run_backup())


def cmd_demo(a):
    from waitwhy.demo import run_demo
    run_demo(publish_now=True, workers=a.workers)


def main(argv=None):
    p = argparse.ArgumentParser(prog="waitwhy")
    p.add_argument("--log-level", default="INFO")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("migrate").set_defaults(fn=cmd_migrate)
    sub.add_parser("init", help="create org/brand/platform rows + seed topic backlog").set_defaults(fn=cmd_init)
    w = sub.add_parser("worker")
    w.add_argument("--types", default="")
    w.set_defaults(fn=cmd_worker)
    sub.add_parser("scheduler").set_defaults(fn=cmd_scheduler)
    ap = sub.add_parser("api")
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=8000)
    ap.set_defaults(fn=cmd_api)
    pr = sub.add_parser("produce", help="start production for a topic title")
    pr.add_argument("topic")
    pr.add_argument("--category", default="everyday_mysteries")
    pr.add_argument("--angle", default="")
    pr.set_defaults(fn=cmd_produce)
    r = sub.add_parser("run", help="process queued jobs until idle")
    r.add_argument("--max-jobs", type=int, default=200)
    r.set_defaults(fn=cmd_run)
    a = sub.add_parser("approve")
    a.add_argument("slug")
    a.add_argument("--kind", default="publication")
    a.add_argument("--decision", default="approved", choices=["approved", "rejected", "changes_requested"])
    a.add_argument("--notes", default="")
    a.add_argument("--user", default="owner")
    a.set_defaults(fn=cmd_approve)
    im = sub.add_parser("import-episodes", help="import finished episodes from channel/episodes.json")
    im.add_argument("--file", default="")
    im.add_argument("--pull", action="store_true", help="git pull --ff-only first")
    im.set_defaults(fn=cmd_import)
    sub.add_parser("report").set_defaults(fn=cmd_report)
    sub.add_parser("tick", help="enqueue due scheduled jobs once").set_defaults(fn=cmd_tick)
    sub.add_parser("backup").set_defaults(fn=cmd_backup)
    d = sub.add_parser("demo", help="dry-run the full lifecycle for the traffic-jam explainer")
    d.add_argument("--workers", type=int, default=3)
    d.set_defaults(fn=cmd_demo)
    args = p.parse_args(argv)
    _setup_logging(args.log_level)
    args.fn(args)


if __name__ == "__main__":
    main()
