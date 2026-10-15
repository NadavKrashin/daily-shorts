"""Publishing metadata (titles, captions, hashtags, disclosure) - small model, strict validation."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from waitwhy.agents.base import call_structured
from waitwhy.models import FactCheck, GeneratedAsset, Script, Video
from waitwhy.schemas import PublishMetadata

CLICKBAIT = ("you won't believe", "shocking", "gone wrong", "100%", "insane")


def prepare(session: Session, cfg: dict, video: Video, job_id=None) -> dict:
    script = session.get(Script, video.current_script_id)
    fc = session.execute(select(FactCheck).where(FactCheck.video_id == video.id)
                         .order_by(FactCheck.version.desc())).scalars().first()
    uses_ai = session.execute(select(GeneratedAsset.id).where(
        GeneratedAsset.video_id == video.id, GeneratedAsset.kind.in_(["scene_image", "scene_video"]),
        GeneratedAsset.status == "succeeded")).first() is not None
    sources = (fc.fact_sheet or {}).get("sources", [])[:5]
    res, run = call_structured(
        session, cfg, agent="metadata", task="metadata", prompt_name="metadata", schema=PublishMetadata, video=video,
        prompt_vars={"brand": cfg["business_name"], "title": video.title, "script": script.full_text,
                     "uses_ai": uses_ai, "sponsored": video.is_sponsored, "sources": sources},
        context={"slug": video.slug, "title": video.title}, job_id=job_id)
    md: PublishMetadata = res.parsed
    # Deterministic guards on top of the model's output
    if uses_ai:
        md.disclosure.ai_generated_visuals = True
    if video.is_sponsored:
        md.disclosure.paid_promotion = True
    for field in ("youtube_title", "instagram_caption", "tiktok_caption", "facebook_caption"):
        val = getattr(md, field)
        if any(c in val.lower() for c in CLICKBAIT):
            run.decision = f"clickbait phrase removed from {field}"
    video.publish_metadata = md.model_dump(mode="json")
    video.disclosures = md.disclosure.model_dump()
    return video.publish_metadata
