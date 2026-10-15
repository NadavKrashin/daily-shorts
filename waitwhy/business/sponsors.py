"""Sponsorship discovery, rate guidance and outreach DRAFTS. Nothing is ever sent automatically:
sending requires outreach_sending_enabled AND an approved 'outreach' approval per draft."""
from __future__ import annotations

import statistics

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from waitwhy.agents.base import call_structured, record_decision
from waitwhy.analytics import metrics as m
from waitwhy.models import OutreachDraft, Sponsor
from waitwhy.providers import registry

SECTORS = ["educational technology", "science learning", "technology software", "consumer electronics",
           "language learning", "productivity tools", "educational subscriptions"]


class Prospect(BaseModel):
    company: str
    website: str
    product: str
    sector: str
    fit_reason: str
    video_concept: str
    contact_source: str


class ProspectList(BaseModel):
    prospects: list[Prospect]


def research(session: Session, cfg: dict, job_id=None) -> dict:
    if registry.llm(cfg).name == "mock":
        record_decision(session, "business", "sponsor_research", "skipped: needs a live LLM with web access")
        return {"skipped": "mock llm"}
    existing = [s.company for s in session.execute(select(Sponsor)).scalars()]
    facts = channel_facts(session)
    res, run = call_structured(session, cfg, agent="business", task="strategy", prompt_name="sponsorship_research",
                               schema=ProspectList, job_id=job_id,
                               prompt_vars={"channel_facts": facts, "sectors": SECTORS, "existing": existing})
    added = 0
    for p in res.parsed.prospects:
        if p.company in existing:
            continue
        session.add(Sponsor(company=p.company, website=p.website, product=p.product, sector=p.sector,
                            fit_reason=p.fit_reason, video_concept=p.video_concept, contact_source=p.contact_source,
                            status="prospect"))
        added += 1
    run.decision = f"{added} new sponsor prospects (drafts only, no contact made)"
    return {"added": added}


def channel_facts(session: Session) -> dict:
    rows = m.all_post_metrics(session)
    v7 = [r.windows["7d"] for r in rows if r.windows.get("7d") is not None]
    return {"public_posts": len(rows), "median_7d_views": statistics.median(v7) if v7 else None,
            "audience": "curious English-speaking viewers 16-35 (target; demographics unverified until platform data)"}


def rate_guidance(session: Session, cfg: dict, cpm_low: float = 15.0, cpm_high: float = 35.0) -> dict:
    """Suggested flat fee per integrated short = median 7-day reach x assumed CPM range.
    CPMs are ASSUMPTIONS to calibrate against real offers, not market facts or expected revenue."""
    rows = m.all_post_metrics(session)
    v7 = [r.windows["7d"] for r in rows if r.windows.get("7d") is not None]
    if len(v7) < 5:
        return {"status": "insufficient_data", "posts_with_7d": len(v7),
                "note": "Need >= 5 published videos with 7-day metrics before quoting rates."}
    med = statistics.median(v7)
    return {"status": "ok", "median_7d_views": med, "assumed_cpm_range_usd": [cpm_low, cpm_high],
            "suggested_fee_range_usd": [round(med / 1000 * cpm_low, -1), round(med / 1000 * cpm_high, -1)],
            "adjust_for": ["exclusivity (+)", "usage rights / paid amplification (+)", "multi-deliverable bundles",
                           "production complexity"],
            "note": "Guidance only - not a revenue forecast."}


def draft_outreach(session: Session, cfg: dict, sponsor: Sponsor) -> OutreachDraft:
    facts = channel_facts(session)
    body = (f"Hi {sponsor.company} team,\n\nI run {cfg['business_name']}, a channel of 60-second animated "
            f"explainers for curious learners ({cfg['tagline']}).\n\nWhy {sponsor.product}: {sponsor.fit_reason}\n\n"
            f"Idea: {sponsor.video_concept}\n\nCurrent reach: "
            f"{'median ' + format(int(facts['median_7d_views']), ',') + ' views in 7 days' if facts['median_7d_views'] else 'we are a new channel - happy to share live stats'}.\n"
            "Sponsored videos are clearly disclosed and we never compromise scientific accuracy.\n\n"
            "Would you be open to a short call?\n\nBest,\n[Owner name]")
    d = OutreachDraft(sponsor_id=sponsor.id, subject=f"{cfg['business_name']} x {sponsor.company}", body=body,
                      status="draft")
    session.add(d)
    sponsor.status = "drafted"
    session.flush()
    return d
