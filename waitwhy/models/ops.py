"""Publishing, analytics, experiments, jobs, agent runs, provider usage."""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Float, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, IdMixin, TimestampMixin, utcnow


class PublicationJob(IdMixin, TimestampMixin, Base):
    """One video x one platform. Its idempotency key guarantees at-most-once publication."""

    __tablename__ = "publication_jobs"
    video_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("videos.id", ondelete="CASCADE"), index=True)
    video_version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("video_versions.id"))
    platform: Mapped[str] = mapped_column(String(32))
    platform_account_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("platform_accounts.id"))
    idempotency_key: Mapped[str] = mapped_column(String(200), unique=True)
    status: Mapped[str] = mapped_column(String(40), default="scheduled", index=True)
    # scheduled | uploading | processing | published | private_uploaded | manual_action_required
    # | failed | blocked | cancelled
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text)
    error_class: Mapped[str | None] = mapped_column(String(32))  # transient | permanent | auth | policy
    external_upload_id: Mapped[str | None] = mapped_column(String(200))   # resumable session / container id
    metadata_: Mapped[dict] = mapped_column("metadata", default=dict)  # title/caption/hashtags/disclosures
    dry_run: Mapped[bool] = mapped_column(Boolean, default=True)
    __table_args__ = (UniqueConstraint("video_id", "platform", name="uq_publication_video_platform"),)


class PlatformPost(IdMixin, TimestampMixin, Base):
    __tablename__ = "platform_posts"
    publication_job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("publication_jobs.id"), unique=True)
    video_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("videos.id", ondelete="CASCADE"), index=True)
    platform: Mapped[str] = mapped_column(String(32), index=True)
    external_id: Mapped[str] = mapped_column(String(200))
    url: Mapped[str | None] = mapped_column(Text)
    privacy_status: Mapped[str] = mapped_column(String(32))  # public | private | unlisted | self_only
    is_public: Mapped[bool] = mapped_column(Boolean, default=False)
    is_mock: Mapped[bool] = mapped_column(Boolean, default=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (UniqueConstraint("platform", "external_id"),)


class AnalyticsSnapshot(IdMixin, Base):
    """Point-in-time platform metrics. NULL means 'not available from this API', never zero."""

    __tablename__ = "analytics_snapshots"
    platform_post_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("platform_posts.id", ondelete="CASCADE"), index=True)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    hours_since_publish: Mapped[float] = mapped_column(Float)
    views: Mapped[int | None] = mapped_column(BigInteger)
    reach: Mapped[int | None] = mapped_column(BigInteger)
    likes: Mapped[int | None] = mapped_column(BigInteger)
    comments: Mapped[int | None] = mapped_column(BigInteger)
    shares: Mapped[int | None] = mapped_column(BigInteger)
    saves: Mapped[int | None] = mapped_column(BigInteger)
    followers_gained: Mapped[int | None] = mapped_column(BigInteger)
    avg_view_duration_s: Mapped[float | None] = mapped_column(Float)
    avg_pct_viewed: Mapped[float | None] = mapped_column(Float)
    completion_rate: Mapped[float | None] = mapped_column(Float)
    retention_curve: Mapped[list | None] = mapped_column(default=None)
    estimated_revenue_usd: Mapped[float | None] = mapped_column(Numeric(12, 4))
    is_preliminary: Mapped[bool] = mapped_column(Boolean, default=True)
    is_mock: Mapped[bool] = mapped_column(Boolean, default=False)
    supersedes_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("analytics_snapshots.id"))  # platform corrections
    raw: Mapped[dict] = mapped_column(default=dict)
    __table_args__ = (UniqueConstraint("platform_post_id", "captured_at"),)


class Experiment(IdMixin, TimestampMixin, Base):
    __tablename__ = "experiments"
    hypothesis: Mapped[str] = mapped_column(Text)
    change: Mapped[str] = mapped_column(Text)
    metric: Mapped[str] = mapped_column(String(128))
    cohort_definition: Mapped[dict] = mapped_column(default=dict)
    start_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    end_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sample_size: Mapped[int] = mapped_column(Integer, default=0)
    video_ids: Mapped[list] = mapped_column(default=list)
    status: Mapped[str] = mapped_column(String(32), default="proposed")  # proposed|running|concluded|abandoned
    outcome: Mapped[str | None] = mapped_column(Text)
    confidence_limitations: Mapped[str | None] = mapped_column(Text)
    follow_up: Mapped[str | None] = mapped_column(Text)


class WorkflowJob(IdMixin, Base):
    """Durable job queue row (Postgres SELECT ... FOR UPDATE SKIP LOCKED)."""

    __tablename__ = "workflow_jobs"
    type: Mapped[str] = mapped_column(String(64), index=True)
    payload: Mapped[dict] = mapped_column(default=dict)
    status: Mapped[str] = mapped_column(String(16), default="queued")
    # queued | running | succeeded | failed(retry pending) | dead | cancelled | blocked
    priority: Mapped[int] = mapped_column(Integer, default=0)
    run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=5)
    timeout_s: Mapped[int] = mapped_column(Integer, default=900)
    idempotency_key: Mapped[str | None] = mapped_column(String(300), unique=True)
    locked_by: Mapped[str | None] = mapped_column(String(128))
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    error_class: Mapped[str | None] = mapped_column(String(32))
    result: Mapped[dict | None] = mapped_column(default=None)
    video_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("videos.id", ondelete="SET NULL"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (Index("ix_jobs_claim", "status", "run_at", "priority"),)


class AgentRun(IdMixin, Base):
    __tablename__ = "agent_runs"
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    agent: Mapped[str] = mapped_column(String(64), index=True)
    task: Mapped[str] = mapped_column(String(64))
    video_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("videos.id", ondelete="SET NULL"), index=True)
    job_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("workflow_jobs.id", ondelete="SET NULL"))
    status: Mapped[str] = mapped_column(String(16))  # succeeded | failed
    provider: Mapped[str | None] = mapped_column(String(64))
    model: Mapped[str | None] = mapped_column(String(128))
    prompt_name: Mapped[str | None] = mapped_column(String(128))
    prompt_version: Mapped[str | None] = mapped_column(String(32))
    input: Mapped[dict] = mapped_column(default=dict)
    output: Mapped[dict | None] = mapped_column(default=None)
    decision: Mapped[str | None] = mapped_column(Text)  # one-line summary for the dashboard feed
    tokens_in: Mapped[int | None] = mapped_column(Integer)
    tokens_out: Mapped[int | None] = mapped_column(Integer)
    cost_usd: Mapped[float] = mapped_column(Numeric(10, 4), default=0)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    error: Mapped[str | None] = mapped_column(Text)


class ProviderUsage(IdMixin, Base):
    __tablename__ = "provider_usage"
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    provider: Mapped[str] = mapped_column(String(64), index=True)
    model: Mapped[str | None] = mapped_column(String(128))
    kind: Mapped[str] = mapped_column(String(32))  # llm | image | video | tts | render | storage
    video_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("videos.id", ondelete="SET NULL"), index=True)
    agent_run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("agent_runs.id", ondelete="SET NULL"))
    asset_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("generated_assets.id", ondelete="SET NULL"))
    units: Mapped[dict] = mapped_column(default=dict)  # {"input_tokens":..} / {"seconds":..} / {"characters":..}
    cost_usd: Mapped[float] = mapped_column(Numeric(10, 4), default=0)
    is_estimate: Mapped[bool] = mapped_column(Boolean, default=True)
    is_mock: Mapped[bool] = mapped_column(Boolean, default=False)
    month: Mapped[str] = mapped_column(String(7), index=True)  # YYYY-MM (UTC)
