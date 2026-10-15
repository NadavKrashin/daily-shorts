"""Shared agent plumbing: prompt rendering, LLM call, budget pre-check, usage + agent_run records."""
from __future__ import annotations

import time
from typing import Any

from pydantic import BaseModel
from sqlalchemy.orm import Session

from waitwhy import prompts
from waitwhy.business import budget
from waitwhy.models import AgentRun, Video
from waitwhy.providers import registry

# Conservative pre-call estimates (USD) used for the budget check before an LLM call.
LLM_PRECHECK_USD = {"research": 0.60, "factcheck": 0.25, "script": 0.20, "storyboard": 0.30, "qa": 0.25,
                    "strategy": 0.20, "metadata": 0.01, "classify": 0.01, "topic_scoring": 0.02}


def call_structured(session: Session, cfg: dict, *, agent: str, task: str, prompt_name: str, prompt_vars: dict,
                    schema: type[BaseModel], video: Video | None = None, context: dict | None = None,
                    job_id=None, max_tokens: int = 16000, images: list | None = None) -> tuple[Any, AgentRun]:
    llm = registry.llm(cfg)
    model = cfg["models"].get(task, "claude-opus-5-5")
    effort = cfg.get("llm_effort", {}).get(task, "medium")
    if llm.name != "mock":
        budget.check(session, cfg, LLM_PRECHECK_USD.get(task, 0.2), f"{agent}:{task}", video)
    p = prompts.render(prompt_name, **prompt_vars)
    started = time.monotonic()
    run = AgentRun(agent=agent, task=task, video_id=video.id if video else None, job_id=job_id,
                   provider=llm.name, model=model, prompt_name=p.name, prompt_version=p.version,
                   input={"vars": _summarize(prompt_vars)}, status="running")
    session.add(run)
    session.flush()
    try:
        res = llm.structured(task=task, system=p.system, prompt=p.user, schema=schema, model=model, effort=effort,
                             max_tokens=max_tokens, context=context, images=images)
    except Exception as e:
        run.status, run.error = "failed", f"{type(e).__name__}: {e}"
        run.duration_ms = int((time.monotonic() - started) * 1000)
        session.flush()
        raise
    run.status = "succeeded"
    run.output = res.parsed.model_dump(mode="json")
    run.tokens_in, run.tokens_out, run.cost_usd = res.input_tokens, res.output_tokens, res.cost_usd
    run.model = res.model
    run.duration_ms = int((time.monotonic() - started) * 1000)
    budget.record_usage(session, cfg, provider=llm.name, model=res.model, kind="llm", cost_usd=res.cost_usd,
                        video_id=video.id if video else None, is_mock=res.is_mock or llm.name == "mock",
                        units={"input_tokens": res.input_tokens, "output_tokens": res.output_tokens},
                        agent_run_id=run.id)
    run.input["is_mock_output"] = res.is_mock
    return res, run


def record_decision(session: Session, agent: str, task: str, decision: str, video: Video | None = None,
                    output: dict | None = None, status: str = "succeeded") -> AgentRun:
    run = AgentRun(agent=agent, task=task, video_id=video.id if video else None, status=status,
                   decision=decision, output=output or {}, provider="rules", model=None)
    session.add(run)
    session.flush()
    return run


def _summarize(vars: dict) -> dict:
    out = {}
    for k, v in vars.items():
        s = repr(v)
        out[k] = s if len(s) < 300 else s[:300] + "..."
    return out
