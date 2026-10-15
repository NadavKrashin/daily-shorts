"""Daily CEO digest, weekly review, monthly management report.

Built deterministically from the database. Every number is labelled; disconnected integrations are
reported as UNKNOWN, never estimated. An optional LLM narrative may only restate the given facts.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from waitwhy.agents.base import record_decision
from waitwhy.agents.coo import credential_status, inventory
from waitwhy.analytics import metrics as m
from waitwhy.business import budget, finance
from waitwhy.models import Approval, Notification, PlatformPost, PublicationJob, SystemSetting, Video
from waitwhy.notify import send


def _fmt(v, unit=""):
    return "UNKNOWN" if v is None else f"{v:,.0f}{unit}" if isinstance(v, (int, float)) else str(v)


def daily_facts(session: Session, cfg: dict) -> dict:
    now = datetime.now(timezone.utc)
    yday = now - timedelta(days=1)
    published_y = session.execute(select(PlatformPost).where(PlatformPost.published_at >= yday,
                                                             PlatformPost.is_public.is_(True),
                                                             PlatformPost.is_mock.is_(False))).scalars().all()
    mock_y = session.execute(select(func.count()).select_from(PlatformPost).where(
        PlatformPost.published_at >= yday, PlatformPost.is_mock.is_(True))).scalar()
    rows = [r for r in m.all_post_metrics(session, include_mock=False)]
    recent = [r for r in rows if (r.latest.get("hours_since_publish") or 1e9) <= 24 * 14]
    views = [r.latest.get("views") for r in recent]
    known = [v for v in views if v is not None]
    strongest = max(recent, key=lambda r: r.latest.get("views") or -1, default=None)
    weakest = min([r for r in recent if r.latest.get("views") is not None and (r.latest.get("hours_since_publish") or 0) >= 72],
                  key=lambda r: r.latest["views"], default=None)
    followers = [r.latest.get("followers_gained") for r in recent]
    st = budget.status(session, cfg)
    inv = inventory(session)
    scheduled = session.execute(select(PublicationJob).where(PublicationJob.status == "scheduled")
                                .order_by(PublicationJob.scheduled_at)).scalars().all()
    attention = session.execute(select(Notification).where(Notification.acknowledged_at.is_(None),
                                                           Notification.severity.in_(["critical", "high"]))
                                .order_by(Notification.created_at.desc()).limit(10)).scalars().all()
    pending = session.execute(select(func.count()).select_from(Approval).where(Approval.status == "pending")).scalar()
    creds = credential_status()
    platforms_connected = {p: creds.get({"tiktok": "tiktok_direct_post"}.get(p, p), False) for p in cfg["platforms"]}
    return {
        "date": now.date().isoformat(),
        "mode": cfg["operating_mode"], "dry_run": cfg.get("dry_run_mode"),
        "videos_published_yesterday": len({p.video_id for p in published_y}),
        "posts_published_yesterday": len(published_y),
        "dry_run_mock_posts_24h": mock_y,
        "recent_views_total": sum(known) if known and len(known) == len(views) else (sum(known) if known else None),
        "recent_views_complete": bool(views) and len(known) == len(views),
        "views_note": "sum of per-platform views (not unique viewers)",
        "strongest_recent": {"title": strongest.title, "platform": strongest.platform,
                             "views": strongest.latest.get("views")} if strongest and strongest.latest.get("views") is not None else None,
        "weakest_recent_72h_plus": {"title": weakest.title, "platform": weakest.platform,
                                    "views": weakest.latest.get("views")} if weakest else None,
        "followers_gained_recent": sum(f for f in followers if f is not None) if any(f is not None for f in followers) else None,
        "in_production": inv["in_flight"], "awaiting_approval": pending,
        "scheduled": [{"platform": p.platform, "at": p.scheduled_at.isoformat()} for p in scheduled[:10]],
        "spend_mtd_usd": st["total_spend_usd"], "variable_spend_mtd_usd": st["variable_spend_usd"],
        "budget_usd": st["monthly_budget_usd"], "hard_cap_usd": st["hard_cap_usd"],
        "simulated_spend_usd": st["simulated_usage_usd"],
        "production_cost_avg_usd": finance.avg_cost_per_published_video(session),
        "confirmed_revenue_mtd_usd": finance.revenue_mtd(session, "received"),
        "attention": [f"[{n.severity}] {n.title}" for n in attention],
        "platforms_connected": platforms_connected,
        "inventory": {k: v for k, v in inv.items() if k != "by_state"},
    }


def recommendations(f: dict, cfg: dict) -> list[str]:
    recs = []
    if f["awaiting_approval"]:
        recs.append(f"Review {f['awaiting_approval']} pending approval(s) in the dashboard (publishing waits on you).")
    if not any(f["platforms_connected"].values()) and not f["dry_run"]:
        recs.append("Connect at least one publishing platform (YouTube first) - nothing can go live yet.")
    if f["dry_run"]:
        recs.append("System is in DRY-RUN: connect API keys (Anthropic, ElevenLabs) and switch dry_run_mode off to "
                    "produce publishable videos.")
    if f["inventory"]["candidate_topics"] < cfg["inventory_targets"]["candidate_topics"]:
        recs.append("Topic backlog below target - trend discovery has been queued.")
    if f["attention"]:
        recs.append(f"Resolve {len(f['attention'])} open high/critical alert(s).")
    if f["budget_usd"] and f["spend_mtd_usd"] / f["budget_usd"] > 0.8:
        recs.append("Spend is above 80% of budget - prefer programmatic scenes and pause AI video generation.")
    return recs[:3] or ["No action needed today."]


def render_daily(f: dict, recs: list[str]) -> str:
    lines = [f"WAIT, WHY? - daily CEO report {f['date']}  (mode: {f['mode']}{', DRY RUN' if f['dry_run'] else ''})", "",
             "VERIFIED FACTS",
             f"- Videos published (last 24h): {f['videos_published_yesterday']} "
             f"({f['posts_published_yesterday']} platform posts; {f['dry_run_mock_posts_24h']} dry-run mock posts excluded)",
             f"- Recent views (14d, {f['views_note']}): {_fmt(f['recent_views_total'])}"
             + ("" if f["recent_views_complete"] else
                (" (no real posts yet)" if f["recent_views_total"] is None and not f["posts_published_yesterday"]
                 and not f["strongest_recent"] else " (some platforms not reporting)")),
             f"- Strongest recent: {f['strongest_recent'] or 'UNKNOWN / no data'}",
             f"- Weakest recent (>=72h old): {f['weakest_recent_72h_plus'] or 'UNKNOWN / no data'}",
             f"- Followers gained (recent): {_fmt(f['followers_gained_recent'])}",
             f"- In production: {f['in_production']}; awaiting approval: {f['awaiting_approval']}",
             f"- Scheduled: {len(f['scheduled'])} " + ", ".join(f"{s['platform']}@{s['at'][:16]}" for s in f["scheduled"][:5]),
             f"- Spend MTD: ${f['spend_mtd_usd']:.2f} of ${f['budget_usd']:.0f} (variable ${f['variable_spend_mtd_usd']:.2f},"
             f" cap ${f['hard_cap_usd']:.0f}; simulated dry-run usage ${f['simulated_spend_usd']:.2f})",
             f"- Avg production cost / published video: {_fmt(f['production_cost_avg_usd'], ' USD')}",
             f"- Confirmed revenue MTD: ${f['confirmed_revenue_mtd_usd']:.2f}",
             "", "NEEDS ATTENTION"] + [f"- {a}" for a in f["attention"] or ["nothing open"]] + \
            ["", "UNKNOWNS"] + [f"- {p}: not connected - metrics unavailable" for p, ok in f["platforms_connected"].items() if not ok] + \
            ["", "RECOMMENDED ACTIONS"] + [f"{i}. {r}" for i, r in enumerate(recs, 1)]
    return "\n".join(lines)


def send_daily(session: Session, cfg: dict) -> dict:
    f = daily_facts(session, cfg)
    recs = recommendations(f, cfg)
    text = render_daily(f, recs)
    _deliver(session, cfg, f"Wait, Why? daily report {f['date']}", text, "last_daily_report")
    record_decision(session, "coo", "daily_report", recs[0], output={"facts": f, "recommendations": recs})
    return {"sent": True, "recommendations": recs}


def send_weekly(session: Session, cfg: dict) -> dict:
    now = datetime.now(timezone.utc)
    week = now - timedelta(days=7)
    rows = m.all_post_metrics(session)
    pub = session.execute(select(func.count()).select_from(PlatformPost).where(PlatformPost.published_at >= week,
                                                                               PlatformPost.is_public.is_(True),
                                                                               PlatformPost.is_mock.is_(False))).scalar()
    jobs = session.execute(select(PublicationJob).where(PublicationJob.updated_at >= week)).scalars().all()
    ok = sum(j.status == "published" for j in jobs)
    st = budget.status(session, cfg)
    cats = m.cohort_stats(rows, "category")
    text = "\n".join([
        f"WAIT, WHY? - weekly review (week ending {now.date()})",
        f"- Public posts this week: {pub}",
        f"- Publishing reliability: {ok}/{len(jobs)} publication jobs published"
        if jobs else "- Publishing reliability: no publication jobs this week",
        f"- 7-day performance by category (medians, per platform): {json.dumps(cats) if cats else 'insufficient data'}",
        f"- Spend MTD ${st['total_spend_usd']:.2f} / ${st['monthly_budget_usd']:.0f}",
        f"- Sponsorship pipeline: {finance.sponsor_pipeline_summary(session)}",
        "- Experiments: see dashboard > Analytics > Experiments",
        "Top improvements (impact / effort): 1) ship consistently 5/week before optimising; "
        "2) connect analytics on every platform; 3) A/B hook styles only once n>=5 per cohort.",
    ])
    _deliver(session, cfg, "Wait, Why? weekly review", text, "last_weekly_review")
    return {"sent": True}


def send_monthly(session: Session, cfg: dict) -> dict:
    st = budget.status(session, cfg)
    pubs = session.execute(select(func.count()).select_from(Video).where(Video.state.in_(["PUBLISHED", "ANALYZING"]))).scalar()
    unit = finance.avg_cost_per_published_video(session)
    text = "\n".join([
        f"WAIT, WHY? - monthly management report {st['month']}",
        "1. Executive summary: see sections below (facts only).",
        f"2. Audience: {len(m.all_post_metrics(session))} public posts tracked",
        f"3. Content: {pubs} videos published to date",
        f"4. Financials: spend ${st['total_spend_usd']:.2f} (fixed ${st['fixed_spend_usd']:.2f}, variable "
        f"${st['variable_spend_usd']:.2f}); confirmed revenue ${finance.revenue_mtd(session, 'received'):.2f}",
        f"5. Unit economics: avg cost per published video {_fmt(unit, ' USD')}",
        f"6. Sponsorship pipeline: {finance.sponsor_pipeline_summary(session)}",
        "7. Recommendation: continue at current scale until 7-day data exists for >= 20 videos; do not raise spend "
        "because of a single outlier.",
        f"8. Proposed next-month budget: ${cfg['monthly_budget_usd']} (unchanged; change requires owner approval)",
    ])
    _deliver(session, cfg, f"Wait, Why? monthly report {st['month']}", text, "last_monthly_report")
    return {"sent": True}


def _deliver(session: Session, cfg: dict, subject: str, text: str, key: str) -> None:
    row = session.get(SystemSetting, key)
    payload = {"generated_at": datetime.now(timezone.utc).isoformat(), "text": text}
    if row:
        row.value = payload
    else:
        session.add(SystemSetting(key=key, value=payload, updated_by="agent:coo"))
    for ch in cfg.get("notifications", {}).get("channels", ["log"]):
        try:
            send(ch, subject, text)
        except Exception as e:  # noqa: BLE001 - report still stored for the dashboard
            from waitwhy.notify import alert
            alert(session, "low", "notifications", f"Report delivery via {ch} failed", str(e), dedupe_key=f"deliver:{ch}")
