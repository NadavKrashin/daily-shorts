"""Agent C - Scientific research and fact-checking.

Two LLM steps (search-backed research memo -> structured fact sheet) followed by deterministic gates:
* every cited URL must come from an actual search result (no URLs from model memory);
* every central claim needs >= 2 independent publishers, or one peer-reviewed/primary source;
* URLs are probed to make sure they resolve (configurable);
* high-risk topics (medical/legal/financial/safety/breaking) are routed to a human.
"""
from __future__ import annotations

import time
from datetime import date, datetime, timezone

import httpx
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from waitwhy import prompts
from waitwhy.agents.base import call_structured
from waitwhy.business import budget
from waitwhy.models import AgentRun, FactCheck, ResearchSource, Video
from waitwhy.providers import registry
from waitwhy.schemas import FactSheet

STRONG_TYPES = {"peer_reviewed", "primary"}


def url_resolves(url: str) -> bool | None:
    try:
        r = httpx.head(url, follow_redirects=True, timeout=15, headers={"User-Agent": "Mozilla/5.0 (fact-check bot)"})
        if r.status_code in (403, 405):  # some sites reject HEAD
            r = httpx.get(url, follow_redirects=True, timeout=20, headers={"User-Agent": "Mozilla/5.0"})
        return r.status_code < 400
    except httpx.HTTPError:
        return None  # unknown (network) - not proof of fabrication


def validate(fs: FactSheet, retrieved_urls: set[str] | None, risk_flags: list[str]) -> tuple[str, list[str]]:
    issues: list[str] = []
    valid_sources = {s.id: s for s in fs.sources}
    if retrieved_urls is not None:
        for s in fs.sources:
            if s.url not in retrieved_urls:
                issues.append(f"source {s.id} ({s.url}) was not returned by search - removed")
                valid_sources.pop(s.id, None)
    for c in fs.claims:
        srcs = [valid_sources[i] for i in c.source_ids if i in valid_sources]
        publishers = {s.publisher.strip().lower() for s in srcs}
        strong = any(s.source_type in STRONG_TYPES for s in srcs)
        if c.status == "verified" and not (len(publishers) >= 2 or strong):
            issues.append(f"claim {c.id} marked verified without 2 independent or 1 primary source - downgraded")
            c.status = "partially_verified"
        if not srcs and c.status in ("verified", "partially_verified"):
            issues.append(f"claim {c.id} has no valid sources - unverified")
            c.status = "unverified"
    central = [c for c in fs.claims if c.importance == "central"]
    if fs.verdict == "reject" or any(c.status == "false" for c in central):
        return "rejected", issues
    if not central or any(c.status != "verified" for c in central):
        return "needs_research", issues + ["not every central claim is verified"]
    if fs.risk_level == "high" or risk_flags:
        return "needs_human", issues + [f"high-risk topic ({', '.join(risk_flags) or fs.risk_level}) requires human review"]
    return "verified", issues


def run(session: Session, cfg: dict, video: Video, job_id=None) -> FactCheck:
    topic = video.topic
    llm = registry.llm(cfg)
    ctx = {"slug": video.slug, "title": video.title}
    model = cfg["models"]["research"]
    if llm.name != "mock":
        budget.check(session, cfg, 0.60, "research", video)
    p = prompts.render("research", title=video.title, angle=topic.angle or "")
    started = time.monotonic()
    res = llm.research(system=p.system, prompt=p.user, model=model, effort=cfg["llm_effort"]["research"], context=ctx)
    rrun = AgentRun(agent="research", task="research", video_id=video.id, job_id=job_id, provider=llm.name,
                    model=res.model, prompt_name=p.name, prompt_version=p.version, status="succeeded",
                    input={"title": video.title}, output={"hits": [h.__dict__ for h in res.hits], "memo": res.memo[:4000]},
                    tokens_in=res.input_tokens, tokens_out=res.output_tokens, cost_usd=res.cost_usd,
                    duration_ms=int((time.monotonic() - started) * 1000),
                    decision=f"{len(res.hits)} sources retrieved, {res.searches} searches")
    session.add(rrun)
    session.flush()
    budget.record_usage(session, cfg, provider=llm.name, model=res.model, kind="llm", cost_usd=res.cost_usd,
                        video_id=video.id, is_mock=res.is_mock or llm.name == "mock", agent_run_id=rrun.id,
                        units={"input_tokens": res.input_tokens, "output_tokens": res.output_tokens,
                               "web_searches": res.searches})

    fs_res, frun = call_structured(
        session, cfg, agent="factcheck", task="factcheck", prompt_name="factcheck",
        prompt_vars={"title": video.title, "hits": res.hits, "memo": res.memo, "today": date.today().isoformat()},
        schema=FactSheet, video=video, context=ctx, job_id=job_id)
    fs: FactSheet = fs_res.parsed
    is_mock = res.is_mock or fs_res.is_mock
    retrieved = {h.url for h in res.hits} if res.hits else (None if is_mock else set())
    status, issues = validate(fs, retrieved, topic.risk_flags or [])

    if cfg.get("verify_source_urls", True) and not cfg.get("dry_run_mode"):
        for s in fs.sources:
            if s.id and url_resolves(s.url) is False:
                issues.append(f"source {s.id} URL did not resolve")
    version = (session.execute(select(func.max(FactCheck.version)).where(FactCheck.video_id == video.id)).scalar() or 0) + 1
    fc = FactCheck(video_id=video.id, version=version, status=status, risk_level=fs.risk_level, provider=llm.name,
                   is_mock=is_mock, fact_sheet={**fs.model_dump(mode="json"), "validation_issues": issues})
    session.add(fc)
    session.flush()
    for s in fs.sources:
        session.add(ResearchSource(video_id=video.id, fact_check_id=fc.id, url=s.url, title=s.title,
                                   publisher=s.publisher, source_type=s.source_type, excerpt=s.key_excerpt,
                                   accessed_at=datetime.now(timezone.utc), retrieved_by_tool=retrieved is not None
                                   and s.url in (retrieved or set())))
    frun.decision = f"fact sheet v{version}: {status}; {len(fs.claims)} claims, {len(fs.sources)} sources" + (
        f"; issues: {len(issues)}" if issues else "")
    return fc
