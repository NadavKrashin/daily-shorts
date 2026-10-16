"""Import finished Why in Clay episodes into the publishing pipeline.

Videos are made by the scheduled Claude + Higgsfield runs (``channel/why-in-clay.md``), which append
each episode to ``channel/episodes.json``. This module turns those entries into ``Video`` rows so the
existing approval, scheduling, publishing and analytics machinery handles them like any other video:

    episodes.json entry -> Topic + Video (QUALITY_CHECK) -> VideoVersion (downloaded file)
        -> imported QC review -> auto-approved (autonomous mode) or READY_FOR_REVIEW -> scheduled

Idempotent: an episode already imported with the same video URL is skipped. A new cut (different
``video_url``) replaces the version only while the video is not yet approved or scheduled.
"""
from __future__ import annotations

import logging
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from waitwhy.audit import audit
from waitwhy.media import probe
from waitwhy.models import Approval, QualityReview, Topic, Video, VideoVersion
from waitwhy.notify import alert
from waitwhy.providers import registry
from waitwhy.schemas import PublishMetadata
from waitwhy.settings import ROOT
from waitwhy.states import S, transition

log = logging.getLogger("waitwhy.importer")
ACTOR = "agent:importer"
IMPORTABLE = {"produced_not_published", "ready"}
REPLACEABLE = {S.QUALITY_CHECK.value, S.READY_FOR_REVIEW.value, S.NEEDS_REVISION.value, S.FAILED.value}
PLATFORM_MAX_S = {"youtube": 180, "instagram": 90, "facebook": 90, "tiktok": 600}


def episodes_path(cfg: dict) -> Path:
    p = Path(cfg.get("episodes", {}).get("file", "channel/episodes.json"))
    return p if p.is_absolute() else ROOT / p


def git_pull(repo: Path = ROOT) -> str:
    """Fast-forward the checkout so episodes pushed by the production runs are visible."""
    r = subprocess.run(["git", "-C", str(repo), "pull", "--ff-only"], capture_output=True, text=True, timeout=120)
    if r.returncode != 0:
        raise RuntimeError(f"git pull failed: {r.stderr.strip()[:300]}")
    return r.stdout.strip()


def download(url: str, dest: Path) -> Path:
    if url.startswith("file://"):
        dest.write_bytes(Path(url[7:]).read_bytes())
        return dest
    with httpx.stream("GET", url, timeout=120, follow_redirects=True) as r:
        r.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in r.iter_bytes(1 << 20):
                f.write(chunk)
    return dest


def build_metadata(ep: dict, cfg: dict) -> dict:
    sources = "\n".join(f"- {u}" for u in ep.get("sources", []))
    desc = (ep.get("description") or ep["title"]).strip()
    tags = ep.get("hashtags") or ["#shorts", "#science", "#claymation"]
    caption = (ep.get("caption") or desc.split("\n")[0]).strip()
    md = PublishMetadata(
        youtube_title_candidates=[ep["title"]], youtube_title=ep["title"][:100],
        youtube_description=f"{desc}\n\nSources:\n{sources}\n\nAnimated with AI tools; facts checked against the "
                            "sources above." if sources else desc,
        instagram_caption=f"{caption} {' '.join(tags)}", tiktok_caption=f"{caption} {' '.join(tags)}",
        facebook_caption=caption, hashtags=tags, call_to_action="Follow for one everyday mystery a day.",
        cover_text=ep.get("thumbnail_hook", ""),
        # Clay animation and a stock synthetic narrator: AI-made, but not realistic people or events.
        disclosure={"ai_generated_visuals": True, "realistic_synthetic_media": False, "paid_promotion": False,
                    "notes": "Higgsfield-generated claymation and synthetic narration"})
    return md.model_dump(mode="json")


def review_inputs(cfg: dict, ep: dict) -> dict:
    """Everything outside the video file that the review depends on; a change re-runs the review."""
    return {"rights": bool(cfg.get("episodes", {}).get("higgsfield_commercial_use_confirmed")),
            "checks": ep.get("checks", {}), "sources": len(ep.get("sources", [])),
            "known_issues": ep.get("known_issues", [])}


def review(session: Session, cfg: dict, video: Video, vv: VideoVersion, ep: dict) -> QualityReview:
    """QC for an imported episode: the technical checks the app's own renders get, plus the production
    run's own recorded checks. Visual/narration review already happened in the run (frame strips,
    strict word check); this records it and blocks if the run did not report it."""
    ecfg = cfg.get("episodes", {})
    store = registry.storage(cfg)
    path = store.local_path(vv.storage_key)
    tech = probe.technical_report(path, {**cfg["video"], **ecfg.get("video", {})})
    checks = tech["checks"]
    vv.probe = {k: v for k, v in tech["probe"].items() if k in ("duration_s", "loudness", "black", "silence")}

    def add(name, category, passed, detail, mandatory=True):
        checks.append({"name": name, "category": category, "passed": bool(passed), "mandatory": mandatory,
                       "detail": detail})

    run_checks = ep.get("checks", {})
    add("sources_listed", "accuracy", len(ep.get("sources", [])) >= 2, f"{len(ep.get('sources', []))} sources")
    add("narration_word_check", "accuracy", run_checks.get("narration_strict") == "passed",
        f"strict narration check: {run_checks.get('narration_strict', 'not reported')}")
    add("captions_checked", "subtitles", run_checks.get("captions") == "passed",
        f"captions: {run_checks.get('captions', 'not reported')}")
    add("visual_review", "continuity", run_checks.get("visual_review") == "passed",
        f"frame-strip review: {run_checks.get('visual_review', 'not reported')}")
    rights_ok = bool(ecfg.get("higgsfield_commercial_use_confirmed"))
    add("rights_cleared", "rights", rights_ok, "owner confirmed the Higgsfield plan covers commercial use"
        if rights_ok else "owner has not confirmed the Higgsfield plan covers commercial use "
        "(episodes.higgsfield_commercial_use_confirmed)")
    dur = tech["probe"].get("duration_s") or 0
    too_long = [p for p, mx in PLATFORM_MAX_S.items() if cfg["platforms"].get(p, {}).get("enabled") and dur > mx]
    add("platform_duration_limits", "platform", not too_long, f"too long for {too_long}" if too_long else "ok")
    add("disclosures_resolved", "platform", bool((video.publish_metadata or {}).get("disclosure")), "set on import")
    issues = ep.get("known_issues", [])
    add("no_known_issues", "editorial", not issues, "; ".join(issues) or "none", mandatory=False)

    blocking = [f"{c['name']}: {c['detail']}" for c in checks if c["mandatory"] and not c["passed"]]
    passed = not blocking
    score = round(100 * sum(c["passed"] for c in checks) / max(1, len(checks)), 1)
    rev = QualityReview(video_version_id=vv.id, reviewer="automated:import", passed=passed, score=score,
                        checks=checks, blocking_issues=blocking, repair_scenes=[],
                        notes="PUBLISHABLE" if passed else "FAILED")
    session.add(rev)
    vv.status = "qc_passed" if passed else "qc_failed"
    vv.manifest = {**vv.manifest, "publishable": passed, "review_inputs": review_inputs(cfg, ep)}
    session.flush()
    return rev


def _topic(session: Session, ep: dict) -> Topic:
    t = session.execute(select(Topic).where(Topic.slug == ep["slug"])).scalar_one_or_none()
    if t is None:
        t = Topic(title=ep["title"], slug=ep["slug"], category=ep.get("category", "everyday_mysteries"),
                  angle=ep.get("thumbnail_hook"), summary=ep["title"], origin="claude_run", status="produced",
                  scores={}, risk_flags=[], keywords=[])
        session.add(t)
        session.flush()
    t.status = "produced"
    return t


def _store_version(session: Session, cfg: dict, video: Video, ep: dict, fetch) -> VideoVersion:
    store = registry.storage(cfg)
    n = 1 + max([v for (v,) in session.execute(select(VideoVersion.version)
                                                .where(VideoVersion.video_id == video.id)).all()] or [0])
    with tempfile.TemporaryDirectory(prefix="ww-import-") as d:
        vid = fetch(ep["video_url"], Path(d) / "video.mp4")
        key = store.put_file(vid, f"videos/{video.id}/v{n}.mp4", "video/mp4")
        thumb_key = None
        if ep.get("thumbnail_url"):
            suffix = Path(ep["thumbnail_url"].split("?")[0]).suffix or ".png"
            th = fetch(ep["thumbnail_url"], Path(d) / f"thumb{suffix}")
            thumb_key = store.put_file(th, f"videos/{video.id}/thumb_v{n}{suffix}")
    vv = VideoVersion(video_id=video.id, version=n, storage_key=key, thumbnail_key=thumb_key,
                      manifest={"source": "claude_higgsfield_run", "source_url": ep["video_url"],
                                "episode_number": ep.get("number"), "credits_spent": ep.get("credits_spent"),
                                "sources": ep.get("sources", []),
                                "rights": [{"asset": "Higgsfield generations (video, images, narration)",
                                            "ai_generated": True,
                                            "commercial_use": bool(cfg.get("episodes", {})
                                                                   .get("higgsfield_commercial_use_confirmed"))}]},
                      change_note=f"imported from episodes.json (episode {ep.get('number')})")
    session.add(vv)
    session.flush()
    video.current_version_id = vv.id
    return vv


def import_episode(session: Session, cfg: dict, ep: dict, fetch=download) -> str:
    from waitwhy.pipeline import after_qc

    video = session.execute(select(Video).where(Video.slug == ep["slug"])).scalar_one_or_none()
    if video is not None:
        cur = session.get(VideoVersion, video.current_version_id) if video.current_version_id else None
        if cur is not None and cur.manifest.get("source_url") == ep["video_url"]:
            if video.state != S.NEEDS_REVISION.value or cur.manifest.get("review_inputs") == review_inputs(cfg, ep):
                return "unchanged"
            # Same cut, but something the review depends on changed (e.g. the owner confirmed rights).
            transition(session, video, S.QUALITY_CHECK, ACTOR, "review inputs changed; re-checking")
            video.publish_metadata = build_metadata(ep, cfg)
            video.disclosures = video.publish_metadata["disclosure"]
            cur.manifest = {**cur.manifest, "rights": [{**r, "commercial_use": review_inputs(cfg, ep)["rights"]}
                                                       for r in cur.manifest.get("rights", [])]}
            return f"rechecked: {after_qc(session, cfg, video, review(session, cfg, video, cur, ep), actor=ACTOR)}"
        if video.state not in REPLACEABLE:
            alert(session, "high", "publishing", f"New cut of '{video.title}' not swapped in",
                  f"The video is already {video.state}; replace it by hand if the new cut should go out.",
                  dedupe_key=f"import-late:{video.id}:{ep['video_url']}", video_id=video.id)
            return f"skipped: already {video.state}"
        for ap in session.execute(select(Approval).where(Approval.video_id == video.id,
                                                         Approval.status == "pending")).scalars():
            ap.status = "superseded"
        if video.state != S.NEEDS_REVISION.value:
            transition(session, video, S.NEEDS_REVISION, ACTOR, "new cut imported")
        transition(session, video, S.QUALITY_CHECK, ACTOR, "re-checking the new cut")
        outcome = "replaced"
    else:
        topic = _topic(session, ep)
        video = Video(topic_id=topic.id, title=ep["title"], slug=ep["slug"], category=topic.category,
                      state=S.IDEA.value, state_changed_at=datetime.now(timezone.utc),
                      animation_technique="higgsfield_claymotion", budget_usd=None)
        session.add(video)
        session.flush()
        audit(session, ACTOR, "video.imported", "video", video.id, episode=ep.get("number"), url=ep["video_url"])
        transition(session, video, S.QUALITY_CHECK, ACTOR, "finished episode imported from a production run")
        outcome = "imported"
    video.publish_metadata = build_metadata(ep, cfg)
    video.disclosures = video.publish_metadata["disclosure"]
    vv = _store_version(session, cfg, video, ep, fetch)
    rev = review(session, cfg, video, vv, ep)
    result = after_qc(session, cfg, video, rev, actor=ACTOR)
    return f"{outcome}: {result}"


def import_all(session: Session, cfg: dict, path: Path | None = None, fetch=download) -> dict:
    import json

    path = path or episodes_path(cfg)
    data = json.loads(Path(path).read_text())
    out = {}
    for ep in data.get("episodes", []):
        if ep.get("status") not in IMPORTABLE or not ep.get("video_url"):
            continue
        try:
            with session.begin_nested():
                out[ep["slug"]] = import_episode(session, cfg, ep, fetch)
        except Exception as exc:  # one bad episode must not stop the rest
            log.exception("import failed for %s", ep.get("slug"))
            out[ep["slug"]] = f"failed: {exc}"[:300]
            alert(session, "high", "production", f"Episode import failed: {ep.get('title')}", str(exc)[:900],
                  dedupe_key=f"import-fail:{ep.get('slug')}:{ep.get('video_url')}")
    return out
