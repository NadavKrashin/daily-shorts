"""Content lineage: Topic -> Research -> Script -> Storyboard -> Assets -> Video -> Versions -> QC -> Approvals.

``Video`` is the canonical content item: its id is the stable content ID for the whole lifecycle.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, IdMixin, TimestampMixin


class Topic(IdMixin, TimestampMixin, Base):
    __tablename__ = "topics"
    brand_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("brands.id"))
    title: Mapped[str] = mapped_column(String(300))
    slug: Mapped[str] = mapped_column(String(200))
    category: Mapped[str] = mapped_column(String(64), index=True)
    angle: Mapped[str | None] = mapped_column(Text)
    summary: Mapped[str | None] = mapped_column(Text)
    origin: Mapped[str] = mapped_column(String(64), default="agent")  # agent | seed | owner | analytics
    status: Mapped[str] = mapped_column(String(32), default="candidate", index=True)
    # candidate | evaluated | selected | in_production | produced | rejected | duplicate
    score_total: Mapped[float | None] = mapped_column(Float)
    scores: Mapped[dict] = mapped_column(default=dict)
    score_reasoning: Mapped[str | None] = mapped_column(Text)
    risk_flags: Mapped[list] = mapped_column(default=list)
    requires_human_review: Mapped[bool] = mapped_column(Boolean, default=False)
    duplicate_of_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("topics.id"))
    keywords: Mapped[list] = mapped_column(default=list)
    __table_args__ = (UniqueConstraint("slug"),)


class Video(IdMixin, TimestampMixin, Base):
    """Canonical content item (stable content ID)."""

    __tablename__ = "videos"
    brand_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("brands.id"))
    topic_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("topics.id"))
    title: Mapped[str] = mapped_column(String(300))
    slug: Mapped[str] = mapped_column(String(200), unique=True)
    state: Mapped[str] = mapped_column(String(32), default="IDEA", index=True)
    state_before_block: Mapped[str | None] = mapped_column(String(32))
    state_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    blocked_reason: Mapped[str | None] = mapped_column(Text)
    priority: Mapped[int] = mapped_column(Integer, default=0)
    category: Mapped[str | None] = mapped_column(String(64))
    hook_style: Mapped[str | None] = mapped_column(String(64))        # for cohort analysis
    story_structure: Mapped[str | None] = mapped_column(String(64))
    animation_technique: Mapped[str | None] = mapped_column(String(64))
    requires_human_review: Mapped[bool] = mapped_column(Boolean, default=False)
    is_sponsored: Mapped[bool] = mapped_column(Boolean, default=False)
    sponsorship_deal_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("sponsorship_deals.id", use_alter=True))
    budget_usd: Mapped[float | None] = mapped_column(Numeric(10, 2))
    current_script_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("scripts.id", use_alter=True))
    current_storyboard_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("storyboards.id", use_alter=True))
    current_version_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("video_versions.id", use_alter=True))
    publish_metadata: Mapped[dict] = mapped_column(default=dict)
    disclosures: Mapped[dict] = mapped_column(default=dict)
    stage_timings: Mapped[dict] = mapped_column(default=dict)   # stage -> seconds
    topic = relationship("Topic")


class ResearchSource(IdMixin, TimestampMixin, Base):
    __tablename__ = "research_sources"
    video_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("videos.id", ondelete="CASCADE"), index=True)
    fact_check_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("fact_checks.id", ondelete="CASCADE"))
    url: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text)
    publisher: Mapped[str | None] = mapped_column(String(300))
    source_type: Mapped[str] = mapped_column(String(32))  # peer_reviewed | primary | institution | secondary
    accessed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    excerpt: Mapped[str | None] = mapped_column(Text)
    url_verified: Mapped[bool | None] = mapped_column(Boolean)  # did the URL resolve when checked?
    retrieved_by_tool: Mapped[bool] = mapped_column(Boolean, default=False)  # came from a search tool, not model memory


class FactCheck(IdMixin, TimestampMixin, Base):
    __tablename__ = "fact_checks"
    video_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("videos.id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(32))  # verified | needs_research | rejected | needs_human
    fact_sheet: Mapped[dict] = mapped_column(default=dict)
    risk_level: Mapped[str] = mapped_column(String(16), default="standard")
    provider: Mapped[str | None] = mapped_column(String(64))
    is_mock: Mapped[bool] = mapped_column(Boolean, default=False)
    __table_args__ = (UniqueConstraint("video_id", "version"),)


class Script(IdMixin, TimestampMixin, Base):
    __tablename__ = "scripts"
    video_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("videos.id", ondelete="CASCADE"), index=True)
    fact_check_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("fact_checks.id"))
    version: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(32), default="draft")  # draft | approved | rejected
    data: Mapped[dict] = mapped_column(default=dict)       # full ScriptDraft (hooks, segments, claims...)
    full_text: Mapped[str] = mapped_column(Text, default="")
    word_count: Mapped[int] = mapped_column(Integer, default=0)
    est_duration_s: Mapped[float | None] = mapped_column(Float)
    scores: Mapped[dict] = mapped_column(default=dict)
    is_mock: Mapped[bool] = mapped_column(Boolean, default=False)
    __table_args__ = (UniqueConstraint("video_id", "version"),)


class Storyboard(IdMixin, TimestampMixin, Base):
    __tablename__ = "storyboards"
    video_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("videos.id", ondelete="CASCADE"), index=True)
    script_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("scripts.id"))
    version: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(32), default="draft")
    data: Mapped[dict] = mapped_column(default=dict)       # validated Storyboard JSON (style, objects, scenes)
    __table_args__ = (UniqueConstraint("video_id", "version"),)
    scenes = relationship("StoryboardScene", order_by="StoryboardScene.scene_number", cascade="all, delete-orphan")


class StoryboardScene(IdMixin, TimestampMixin, Base):
    __tablename__ = "storyboard_scenes"
    storyboard_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("storyboards.id", ondelete="CASCADE"))
    scene_number: Mapped[int] = mapped_column(Integer)
    start_s: Mapped[float] = mapped_column(Float)
    end_s: Mapped[float] = mapped_column(Float)
    narration: Mapped[str] = mapped_column(Text)
    render_method: Mapped[str] = mapped_column(String(32))  # programmatic | ai_image | ai_video
    template: Mapped[str | None] = mapped_column(String(64))
    data: Mapped[dict] = mapped_column(default=dict)       # full Scene JSON
    status: Mapped[str] = mapped_column(String(32), default="pending")  # pending|generated|failed|needs_repair
    __table_args__ = (UniqueConstraint("storyboard_id", "scene_number"),)


class GeneratedAsset(IdMixin, TimestampMixin, Base):
    __tablename__ = "generated_assets"
    video_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("videos.id", ondelete="SET NULL"), index=True)
    scene_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("storyboard_scenes.id", ondelete="SET NULL"))
    kind: Mapped[str] = mapped_column(String(32))  # scene_clip | image | narration | music | sfx | captions | thumbnail | reference
    provider: Mapped[str] = mapped_column(String(64))
    model: Mapped[str | None] = mapped_column(String(128))
    prompt: Mapped[str | None] = mapped_column(Text)
    negative_prompt: Mapped[str | None] = mapped_column(Text)
    params: Mapped[dict] = mapped_column(default=dict)
    seed: Mapped[int | None] = mapped_column(Integer)
    reference_asset_ids: Mapped[list] = mapped_column(default=list)
    cache_key: Mapped[str | None] = mapped_column(String(128), index=True)  # sha256 of inputs -> reuse
    external_job_id: Mapped[str | None] = mapped_column(String(200))
    storage_key: Mapped[str | None] = mapped_column(Text)
    duration_s: Mapped[float | None] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(32), default="pending")  # pending|running|succeeded|failed|rejected
    quality_status: Mapped[str] = mapped_column(String(32), default="unreviewed")
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text)
    generation_seconds: Mapped[float | None] = mapped_column(Float)
    estimated_cost_usd: Mapped[float] = mapped_column(Numeric(10, 4), default=0)
    cost_usd: Mapped[float] = mapped_column(Numeric(10, 4), default=0)
    rights: Mapped[dict] = mapped_column(default=dict)  # license, commercial_use, source, attribution
    __table_args__ = (Index("ix_asset_scene_kind", "scene_id", "kind"),)


class Voiceover(IdMixin, TimestampMixin, Base):
    __tablename__ = "voiceovers"
    video_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("videos.id", ondelete="CASCADE"), index=True)
    script_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("scripts.id"))
    provider: Mapped[str] = mapped_column(String(64))
    voice_id: Mapped[str | None] = mapped_column(String(128))
    voice_name: Mapped[str | None] = mapped_column(String(128))
    storage_key: Mapped[str] = mapped_column(Text)
    duration_s: Mapped[float] = mapped_column(Float)
    words_per_minute: Mapped[float | None] = mapped_column(Float)
    segments: Mapped[list] = mapped_column(default=list)  # [{scene_number, start, end, text, words:[{w,s,e}]}]
    rights: Mapped[dict] = mapped_column(default=dict)
    cost_usd: Mapped[float] = mapped_column(Numeric(10, 4), default=0)


class VideoVersion(IdMixin, TimestampMixin, Base):
    __tablename__ = "video_versions"
    video_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("videos.id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    storyboard_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("storyboards.id"))
    voiceover_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("voiceovers.id"))
    storage_key: Mapped[str] = mapped_column(Text)
    captions_key: Mapped[str | None] = mapped_column(Text)
    thumbnail_key: Mapped[str | None] = mapped_column(Text)
    manifest: Mapped[dict] = mapped_column(default=dict)   # assets, rights, scene timings, render params
    probe: Mapped[dict] = mapped_column(default=dict)
    duration_s: Mapped[float | None] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(32), default="rendered")  # rendered | qc_passed | qc_failed
    change_note: Mapped[str | None] = mapped_column(Text)
    __table_args__ = (UniqueConstraint("video_id", "version"),)


class QualityReview(IdMixin, TimestampMixin, Base):
    __tablename__ = "quality_reviews"
    video_version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("video_versions.id", ondelete="CASCADE"), index=True)
    reviewer: Mapped[str] = mapped_column(String(64))  # automated | llm | human:<name>
    passed: Mapped[bool] = mapped_column(Boolean)
    score: Mapped[float | None] = mapped_column(Float)
    checks: Mapped[list] = mapped_column(default=list)          # [{name, category, passed, mandatory, detail}]
    blocking_issues: Mapped[list] = mapped_column(default=list)
    repair_scenes: Mapped[list] = mapped_column(default=list)   # scene numbers to regenerate (targeted repair)
    notes: Mapped[str | None] = mapped_column(Text)


class Approval(IdMixin, TimestampMixin, Base):
    __tablename__ = "approvals"
    video_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("videos.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(32))
    # publication | research | script | spending | commercial | mode_change | setting_change | outreach
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    # pending | approved | rejected | changes_requested | superseded
    reason: Mapped[str] = mapped_column(Text, default="")
    payload: Mapped[dict] = mapped_column(default=dict)
    target_type: Mapped[str | None] = mapped_column(String(64))
    target_id: Mapped[str | None] = mapped_column(String(64))
    decided_by: Mapped[str | None] = mapped_column(String(200))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decision_notes: Mapped[str | None] = mapped_column(Text)
