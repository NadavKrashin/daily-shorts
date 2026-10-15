"""Strategy analysis: cohort comparisons -> hypotheses (never causal claims), experiment proposals."""
from __future__ import annotations

import json

from sqlalchemy.orm import Session

from waitwhy.agents.base import call_structured, record_decision
from waitwhy.analytics import metrics as m
from waitwhy.providers import registry
from waitwhy.schemas import ExecutiveNarrative

MIN_POSTS_FOR_ANALYSIS = 8


def strategy_analysis(session: Session, cfg: dict, job_id=None) -> dict:
    rows = m.all_post_metrics(session)
    observable = [r for r in rows if r.windows.get("7d") is not None]
    stats = {
        "public_posts": len(rows), "posts_with_7d_data": len(observable),
        "baselines_7d": m.platform_baselines(rows),
        "by_category": m.cohort_stats(rows, "category"), "by_hook_style": m.cohort_stats(rows, "hook_style"),
        "by_animation": m.cohort_stats(rows, "animation"),
    }
    if len(observable) < MIN_POSTS_FOR_ANALYSIS:
        decision = (f"Insufficient data for strategy analysis: {len(observable)} posts with 7-day metrics "
                    f"(need {MIN_POSTS_FOR_ANALYSIS}). No strategy changes recommended.")
        record_decision(session, "strategy", "strategy_analysis", decision, output=stats)
        return {"status": "insufficient_data", **stats}
    out = {"status": "analysed", **stats}
    if registry.llm(cfg).name != "mock":
        res, run = call_structured(session, cfg, agent="strategy", task="strategy", prompt_name="performance_analysis",
                                   prompt_vars={"stats": json.dumps(stats, default=str, indent=1)},
                                   schema=ExecutiveNarrative, job_id=job_id)
        out["narrative"] = res.parsed.model_dump()
        run.decision = res.parsed.summary[:300]
    else:
        record_decision(session, "strategy", "strategy_analysis", "cohort statistics computed (no LLM narrative)",
                        output=stats)
    return out
