"""Agent B - Research & trend discovery: proposes, scores and de-duplicates topics into the backlog."""
from __future__ import annotations

import json
import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from waitwhy.agents.base import call_structured, record_decision
from waitwhy.models import Topic
from waitwhy.schemas import TopicBatch, TopicScores
from waitwhy.settings import ROOT

STOP = {"why", "how", "what", "the", "a", "an", "of", "and", "to", "is", "are", "you", "your", "do", "does", "in",
        "on", "it", "its", "can", "out", "from", "with", "for", "but", "not", "so", "that", "this", "when", "work"}


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:180]


def tokens(text: str) -> set[str]:
    toks = set()
    for w in re.findall(r"[a-z0-9]+", text.lower()):
        if w in STOP or len(w) < 3:
            continue
        toks.add(w[:-1] if w.endswith("s") and len(w) > 4 else w)  # crude singularisation
    return toks


def similarity(a: str, b: str) -> float:
    ta, tb = tokens(a), tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / min(len(ta), len(tb))


def find_duplicate(session: Session, title: str, keywords: list[str], threshold: float) -> Topic | None:
    probe = title + " " + " ".join(keywords)
    best, best_s = None, 0.0
    for t in session.execute(select(Topic).where(Topic.status != "rejected")).scalars():
        s = similarity(probe, t.title + " " + " ".join(t.keywords or []))
        if s > best_s:
            best, best_s = t, s
    return best if best_s >= threshold else None


def add_candidate(session: Session, cfg: dict, cand, origin: str = "agent") -> Topic:
    weights = cfg["topic_scoring_weights"]
    scores = cand.scores if isinstance(cand.scores, TopicScores) else TopicScores(**cand.scores)
    total = scores.weighted(weights)
    slug = slugify(cand.title)
    existing = session.execute(select(Topic).where(Topic.slug == slug)).scalar_one_or_none()
    if existing:
        return existing
    dup = find_duplicate(session, cand.title, cand.keywords, cfg.get("duplicate_similarity_threshold", 0.6))
    flags = [f for f in cand.risk_flags if f in cfg.get("high_risk_topic_flags", [])]
    t = Topic(title=cand.title, slug=slug, category=cand.category, angle=cand.angle, summary=cand.summary,
              keywords=cand.keywords, risk_flags=flags, scores=scores.model_dump(), score_total=total,
              score_reasoning=cand.reasoning, origin=origin, requires_human_review=bool(flags),
              status="duplicate" if dup else "evaluated", duplicate_of_id=dup.id if dup else None)
    session.add(t)
    session.flush()
    return t


def seed_backlog(session: Session, cfg: dict) -> int:
    data = json.loads((ROOT / "seeds" / "topics.json").read_text())
    from waitwhy.schemas import TopicCandidate

    n = 0
    for raw in data["topics"]:
        if session.execute(select(Topic).where(Topic.slug == raw["slug"])).scalar_one_or_none():
            continue
        c = TopicCandidate(**{k: v for k, v in raw.items() if k != "slug"})
        add_candidate(session, cfg, c, origin="seed")
        n += 1
    return n


def discover(session: Session, cfg: dict, count: int = 10, job_id=None) -> dict:
    existing = session.execute(select(Topic.title, Topic.slug)).all()
    res, run = call_structured(
        session, cfg, agent="trends", task="topic_scoring", prompt_name="topic_discovery",
        prompt_vars={"brand": cfg["business_name"], "categories": cfg["content_categories"],
                     "existing": [t for t, _ in existing][:200], "performance_notes": "", "count": count},
        schema=TopicBatch, context={"existing_slugs": [s for _, s in existing], "count": count}, job_id=job_id)
    added = dup = 0
    for cand in res.parsed.candidates:
        t = add_candidate(session, cfg, cand)
        if t.status == "duplicate":
            dup += 1
        else:
            added += 1
    run.decision = f"proposed {len(res.parsed.candidates)} topics: {added} new, {dup} near-duplicates"
    return {"added": added, "duplicates": dup}


def choose_next(session: Session, cfg: dict, n: int = 1) -> list[Topic]:
    """Highest-scoring evaluated topics that are not high-risk (those need a human first)."""
    q = (select(Topic).where(Topic.status == "evaluated", Topic.requires_human_review.is_(False),
                             Topic.score_total >= cfg.get("min_topic_score_for_production", 70))
         .order_by(Topic.score_total.desc()).limit(n))
    picks = list(session.execute(q).scalars())
    if picks:
        record_decision(session, "trends", "select_topics",
                        "selected " + ", ".join(f"{t.title} ({t.score_total})" for t in picks))
    return picks
