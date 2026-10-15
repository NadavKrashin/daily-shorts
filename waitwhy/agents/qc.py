"""Editorial + technical quality control. A score is never enough: mandatory checks gate publication.

Blocks if: unsupported material claim, animation contradicts narration (multimodal review), missing
assets, unlicensed/non-commercial assets, invalid render, unresolved disclosure, missing approval.

In dry-run mode, problems caused ONLY by development stand-ins (mock LLM content, the non-commercial dev
voice, mock visuals) are recorded as ``waived_in_dry_run`` so the full lifecycle can be exercised - the
version is still marked ``publishable=False`` and the live publisher refuses it.
"""
from __future__ import annotations

import re
import subprocess
import tempfile
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from waitwhy.agents.base import call_structured
from waitwhy.media import probe
from waitwhy.models import FactCheck, QualityReview, Script, Storyboard, Video, VideoVersion
from waitwhy.providers import registry
from waitwhy.schemas import EditorialReview, FactSheet, ScriptDraft

PLATFORM_MAX_S = {"youtube": 180, "instagram": 90, "facebook": 90, "tiktok": 600}
DEV_STANDIN_CHECKS = {"rights_cleared", "no_mock_content"}


def _norm_words(s: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", s.lower().replace("’", "'"))


def sample_frames(path: Path, times: list[float]) -> list[Path]:
    out = []
    d = Path(tempfile.mkdtemp(prefix="ww-qc-"))
    for i, t in enumerate(times):
        f = d / f"frame_{i:02d}.jpg"
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", f"{t:.2f}", "-i", str(path), "-frames:v", "1",
                        "-vf", "scale=540:-2", "-q:v", "4", str(f)], check=True, timeout=60)
        out.append(f)
    return out


def run(session: Session, cfg: dict, video: Video, job_id=None) -> QualityReview:
    vv = session.get(VideoVersion, video.current_version_id)
    store = registry.storage(cfg)
    path = store.local_path(vv.storage_key)
    tech = probe.technical_report(path, cfg["video"])
    checks: list[dict] = tech["checks"]
    vv.probe = {k: v for k, v in tech["probe"].items() if k in ("duration_s", "loudness", "black", "silence")}

    def add(name, category, passed, detail, mandatory=True):
        checks.append({"name": name, "category": category, "passed": bool(passed), "mandatory": mandatory,
                       "detail": detail})

    # ---- 1. scientific accuracy
    fc = session.execute(select(FactCheck).where(FactCheck.video_id == video.id)
                         .order_by(FactCheck.version.desc())).scalars().first()
    script = session.get(Script, video.current_script_id)
    fs = FactSheet.model_validate({k: v for k, v in fc.fact_sheet.items() if k != "validation_issues"})
    draft = ScriptDraft.model_validate(script.data)
    add("fact_sheet_verified", "accuracy", fc.status == "verified", f"fact sheet v{fc.version}: {fc.status}")
    status = {c.id: c for c in fs.claims}
    bad = [cid for cid in draft.claim_ids if cid not in status or status[cid].status not in ("verified", "partially_verified")]
    add("claims_supported", "accuracy", not bad, f"unsupported claim refs: {bad}" if bad else "all script claims sourced")
    partial_central = [cid for cid in draft.claim_ids if cid in status and status[cid].importance == "central"
                       and status[cid].status != "verified"]
    add("central_claims_verified", "accuracy", not partial_central, f"central claims not fully verified: {partial_central}"
        if partial_central else "ok")
    add("no_mock_content", "accuracy", not (fc.is_mock or script.is_mock),
        "content produced by the mock LLM - not real research" if (fc.is_mock or script.is_mock) else "real content")

    # ---- 2/5. script clarity + subtitle accuracy
    m = vv.manifest
    cap_words, script_words = _norm_words(m.get("caption_text", "")), _norm_words(draft.full_text)
    add("subtitles_match_script", "subtitles", cap_words == script_words,
        f"{len(cap_words)} caption words vs {len(script_words)} script words")
    add("script_length", "clarity", cfg["script"]["min_words"] - 10 <= draft.word_count <= cfg["script"]["max_words"] + 10,
        f"{draft.word_count} words")

    # ---- 3. continuity / sync
    board = session.get(Storyboard, video.current_storyboard_id)
    desync = [s["scene_number"] for s in m.get("scenes", []) if s["narration_end_s"] > s["end_s"] + 0.01]
    add("narration_within_scene", "continuity", not desync, f"scenes where narration overruns: {desync}" if desync else "ok")
    missing_cont = [s.scene_number for s in board.scenes if not s.data.get("continuity")]
    add("continuity_specified", "continuity", not missing_cont, f"scenes w/o continuity rules: {missing_cont}"
        if missing_cont else "ok", mandatory=False)

    # ---- 7. copyright & licensing
    non_commercial = [r["asset"] for r in m.get("rights", []) if not r.get("commercial_use")]
    add("rights_cleared", "rights", not non_commercial,
        f"NOT cleared for commercial use: {non_commercial}" if non_commercial else "all assets cleared")

    # ---- 8. platform restrictions + disclosure
    dur = tech["probe"].get("duration_s") or 0
    too_long = [p for p, mx in PLATFORM_MAX_S.items() if cfg["platforms"].get(p, {}).get("enabled") and dur > mx]
    add("platform_duration_limits", "platform", not too_long, f"too long for {too_long}" if too_long else "ok")
    meta = video.publish_metadata or {}
    uses_ai = any(r.get("ai_generated") for r in m.get("rights", []))
    disc = (meta.get("disclosure") or {})
    disc_ok = bool(meta) and (not uses_ai or disc.get("ai_generated_visuals")) and \
        (not video.is_sponsored or disc.get("paid_promotion"))
    add("disclosures_resolved", "platform", disc_ok, f"metadata={'yes' if meta else 'missing'}, uses_ai={uses_ai}, "
        f"sponsored={video.is_sponsored}, disclosure={disc}")

    # ---- 9. brand
    last = board.scenes[-1]
    has_end = last.template == "end_card" or any(p.get("key") == "end_card_s" for p in last.data.get("template_params", []))
    add("brand_end_card", "brand", has_end, "end card present" if has_end else "no end card", mandatory=False)

    # ---- 10. editorial multimodal review (narration vs visuals)
    repair: list[int] = []
    llm = registry.llm(cfg)
    if llm.name != "mock":
        mids = [(s["start_s"] + s["end_s"]) / 2 for s in m.get("scenes", [])]
        frames = sample_frames(path, mids)
        res, run = call_structured(
            session, cfg, agent="qc", task="qa", prompt_name="qa_review", schema=EditorialReview, video=video,
            prompt_vars={"claims": fs.claims, "scenes": [s.data | {"scene_number": s.scene_number} for s in board.scenes]},
            images=frames, job_id=job_id)
        er: EditorialReview = res.parsed
        add("narration_matches_visuals", "continuity", er.narration_matches_visuals, er.viewer_experience_notes)
        add("no_unsupported_claims_llm", "accuracy", not er.unsupported_claims, "; ".join(er.unsupported_claims) or "ok")
        add("continuity_review", "continuity", not er.continuity_problems, "; ".join(er.continuity_problems) or "ok",
            mandatory=False)
        for prob in er.continuity_problems:
            repair += [int(x) for x in re.findall(r"scene (\d+)", prob.lower())]
    else:
        add("narration_matches_visuals", "continuity", True,
            "SKIPPED: no multimodal model configured (mock LLM) - human reviewer must check", mandatory=False)

    dry = bool(cfg.get("dry_run_mode"))
    blocking, waived = [], []
    for c in checks:
        if c["mandatory"] and not c["passed"]:
            if dry and c["name"] in DEV_STANDIN_CHECKS:
                c["waived_in_dry_run"] = True
                waived.append(f"{c['name']}: {c['detail']}")
            else:
                blocking.append(f"{c['name']}: {c['detail']}")
    passed = not blocking
    publishable = passed and not waived
    if not passed:
        for c in checks:
            if not c["passed"] and c["name"] in ("narration_within_scene",):
                repair += [int(x) for x in re.findall(r"\d+", c["detail"])]
    score = round(100 * sum(c["passed"] for c in checks) / max(1, len(checks)), 1)
    review = QualityReview(video_version_id=vv.id, reviewer="automated" if llm.name == "mock" else "automated+llm",
                           passed=passed, score=score, checks=checks, blocking_issues=blocking,
                           repair_scenes=sorted(set(repair)),
                           notes=("PUBLISHABLE" if publishable else
                                  "NOT PUBLISHABLE (dev stand-ins waived for dry run): " + " | ".join(waived)
                                  if passed else "FAILED"))
    session.add(review)
    vv.status = "qc_passed" if passed else "qc_failed"
    vv.manifest = {**m, "publishable": publishable, "qc_waivers": waived}
    session.flush()
    return review
