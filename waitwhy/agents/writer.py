"""Agent D (scriptwriter) and Agent E (storyboard director)."""
from __future__ import annotations

import re

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from waitwhy.agents.base import call_structured
from waitwhy.errors import QualityGateFailed
from waitwhy.media.templates import TEMPLATES
from waitwhy.models import FactCheck, Script, Storyboard, StoryboardScene, Video
from waitwhy.schemas import FactSheet, ScriptDraft, StoryboardSpec


def check_script(draft: ScriptDraft, fs: FactSheet, cfg: dict) -> list[str]:
    sc = cfg["script"]
    problems = []
    text = draft.full_text.strip()
    low = text.lower()
    for opener in sc["banned_openers"]:
        if low.startswith(opener):
            problems.append(f"script opens with banned phrase '{opener}'")
    wc = draft.word_count
    if not sc["min_words"] - 10 <= wc <= sc["max_words"] + 10:
        problems.append(f"word count {wc} outside {sc['min_words']}-{sc['max_words']}")
    allowed = {c.id for c in fs.claims if c.status in ("verified", "partially_verified")}
    unknown = draft.claim_ids - allowed
    if unknown:
        problems.append(f"script relies on unverified/unknown claims: {sorted(unknown)}")
    if len(draft.alt_hooks) != 3:
        problems.append("exactly three alternative hooks required")
    if not draft.segments or draft.segments[0].beat != "hook":
        problems.append("script must open with a hook segment")
    # sentences with numbers must cite a claim (numbers are where errors hide)
    for s in draft.segments:
        if re.search(r"\d", s.text) and not s.claim_ids:
            problems.append(f"numeric statement without a cited claim: '{s.text[:60]}'")
    return problems


def write_script(session: Session, cfg: dict, video: Video, job_id=None, revision_notes: str = "") -> Script:
    fc = session.execute(select(FactCheck).where(FactCheck.video_id == video.id)
                         .order_by(FactCheck.version.desc())).scalars().first()
    if not fc or fc.status != "verified":
        raise QualityGateFailed("no verified fact sheet - cannot write a script")
    fs = FactSheet.model_validate({k: v for k, v in fc.fact_sheet.items() if k != "validation_issues"})
    notes, draft, run, problems = revision_notes, None, None, []
    for _attempt in range(2):
        res, run = call_structured(
            session, cfg, agent="scriptwriter", task="script", prompt_name="script",
            prompt_vars={"brand": cfg["business_name"], "tagline": cfg["tagline"], "voice": cfg["brand"]["voice"],
                         "min_words": cfg["script"]["min_words"], "max_words": cfg["script"]["max_words"],
                         "wpm": 150, "duration": cfg["video"]["default_duration_seconds"], "title": video.title,
                         "fact_sheet": fs, "revision_notes": notes},
            schema=ScriptDraft, video=video, context={"slug": video.slug, "title": video.title}, job_id=job_id)
        draft = res.parsed
        problems = check_script(draft, fs, cfg)
        if not problems:
            break
        notes = "Fix these problems:\n- " + "\n- ".join(problems)
    version = (session.execute(select(func.max(Script.version)).where(Script.video_id == video.id)).scalar() or 0) + 1
    script = Script(video_id=video.id, fact_check_id=fc.id, version=version, data=draft.model_dump(mode="json"),
                    full_text=draft.full_text, word_count=draft.word_count, est_duration_s=draft.estimated_duration_s(),
                    scores=draft.scores.model_dump(), is_mock=fc.is_mock or res.is_mock,
                    status="rejected" if problems else ("draft" if cfg.get("script_approval_required") else "approved"))
    session.add(script)
    session.flush()
    run.decision = f"script v{version}: {draft.word_count} words, ~{script.est_duration_s}s" + (
        f"; FAILED checks: {problems}" if problems else "")
    if problems:
        raise QualityGateFailed("; ".join(problems))
    video.current_script_id = script.id
    video.hook_style, video.story_structure = draft.hook_style, draft.story_structure
    return script


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def check_storyboard(sb: StoryboardSpec, draft: ScriptDraft, cfg: dict) -> list[str]:
    problems = []
    if _norm(" ".join(s.narration for s in sb.scenes)) != _norm(draft.full_text):
        problems.append("scene narration does not reproduce the approved script word-for-word")
    ai = [s for s in sb.scenes if s.render_method != "programmatic"]
    if len(ai) > cfg["max_ai_scenes_per_video"]:
        problems.append(f"{len(ai)} AI scenes exceeds limit {cfg['max_ai_scenes_per_video']}")
    for s in sb.scenes:
        if s.render_method == "programmatic" and s.template not in TEMPLATES:
            problems.append(f"scene {s.scene_number}: unknown template '{s.template}'")
        if not s.continuity:
            problems.append(f"scene {s.scene_number}: missing continuity requirements")
    if not 8 <= len(sb.scenes) <= 12:
        problems.append(f"{len(sb.scenes)} scenes (target 8-12)")
    return problems


def make_storyboard(session: Session, cfg: dict, video: Video, job_id=None) -> Storyboard:
    script = session.get(Script, video.current_script_id)
    draft = ScriptDraft.model_validate(script.data)
    from waitwhy.media.templates import describe_templates

    pal = ", ".join(f"{k} {v}" for k, v in cfg["brand"]["palette"].items())
    problems, sb, run = [], None, None
    for _ in range(2):
        res, run = call_structured(
            session, cfg, agent="storyboard", task="storyboard", prompt_name="storyboard",
            prompt_vars={"min_scenes": 8, "max_scenes": 12, "visual_style": cfg["brand"]["visual_style"], "palette": pal,
                         "templates": describe_templates(), "max_ai_scenes": cfg["max_ai_scenes_per_video"],
                         "title": video.title, "segments": draft.segments,
                         "est_duration": script.est_duration_s},
            schema=StoryboardSpec, video=video, job_id=job_id, max_tokens=32000,
            context={"slug": video.slug, "title": video.title,
                     "segments": [s.model_dump() for s in draft.segments]})
        sb = res.parsed
        problems = check_storyboard(sb, draft, cfg)
        if not problems:
            break
    version = (session.execute(select(func.max(Storyboard.version)).where(Storyboard.video_id == video.id)).scalar() or 0) + 1
    board = Storyboard(video_id=video.id, script_id=script.id, version=version, data=sb.model_dump(mode="json"),
                       status="rejected" if problems else "approved")
    session.add(board)
    session.flush()
    for s in sb.scenes:
        session.add(StoryboardScene(storyboard_id=board.id, scene_number=s.scene_number, start_s=s.start_s,
                                    end_s=s.end_s, narration=s.narration, render_method=s.render_method,
                                    template=s.template, data=s.model_dump(mode="json")))
    run.decision = f"storyboard v{version}: {len(sb.scenes)} scenes, " \
                   f"{sum(s.render_method != 'programmatic' for s in sb.scenes)} AI scenes" + (
                       f"; FAILED: {problems}" if problems else "")
    if problems:
        raise QualityGateFailed("; ".join(problems))
    video.current_storyboard_id = board.id
    methods = {s.render_method for s in sb.scenes}
    video.animation_technique = "programmatic" if methods == {"programmatic"} else "hybrid"
    return board
