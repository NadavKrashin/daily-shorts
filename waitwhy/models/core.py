"""Organisation, users, brand, platform accounts, settings, audit."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, IdMixin, JSONType, TimestampMixin, utcnow


class Organization(IdMixin, TimestampMixin, Base):
    __tablename__ = "organizations"
    name: Mapped[str] = mapped_column(String(200), unique=True)
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Jerusalem")


class User(IdMixin, TimestampMixin, Base):
    __tablename__ = "users"
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"))
    email: Mapped[str] = mapped_column(String(320), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    role: Mapped[str] = mapped_column(String(32), default="owner")  # owner | editor | viewer


class Brand(IdMixin, TimestampMixin, Base):
    __tablename__ = "brands"
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"))
    name: Mapped[str] = mapped_column(String(200))
    tagline: Mapped[str | None] = mapped_column(String(300))
    style_guide: Mapped[dict] = mapped_column(default=dict)
    voice: Mapped[dict] = mapped_column(default=dict)
    __table_args__ = (UniqueConstraint("organization_id", "name"),)


class PlatformAccount(IdMixin, TimestampMixin, Base):
    """A connected social account. Holds NO secrets - only the name of the env var/secret."""

    __tablename__ = "platform_accounts"
    brand_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("brands.id"))
    platform: Mapped[str] = mapped_column(String(32))  # youtube | instagram | facebook | tiktok
    account_name: Mapped[str | None] = mapped_column(String(200))
    external_id: Mapped[str | None] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(32), default="disconnected")
    publishing_mode: Mapped[str] = mapped_column(String(64), default="manual_handoff")
    capabilities: Mapped[dict] = mapped_column(default=dict)
    secret_ref: Mapped[str | None] = mapped_column(String(200))
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notes: Mapped[str | None] = mapped_column(Text)
    __table_args__ = (UniqueConstraint("brand_id", "platform"),)


class SystemSetting(Base):
    __tablename__ = "system_settings"
    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    value: Mapped[Any] = mapped_column(JSONType, default=None)
    updated_by: Mapped[str | None] = mapped_column(String(200))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class AuditLog(IdMixin, Base):
    __tablename__ = "audit_logs"
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    actor: Mapped[str] = mapped_column(String(200))  # system | agent:<name> | user:<name> | scheduler
    action: Mapped[str] = mapped_column(String(128), index=True)
    entity_type: Mapped[str | None] = mapped_column(String(64))
    entity_id: Mapped[str | None] = mapped_column(String(64))
    before: Mapped[dict | None] = mapped_column(default=None)
    after: Mapped[dict | None] = mapped_column(default=None)
    details: Mapped[dict] = mapped_column(default=dict)
    __table_args__ = (Index("ix_audit_entity", "entity_type", "entity_id"),)


class Notification(IdMixin, TimestampMixin, Base):
    """Alerts + incidents. Acknowledged from the dashboard; never silently dropped."""

    __tablename__ = "notifications"
    severity: Mapped[str] = mapped_column(String(16), index=True)  # critical | high | low | info
    category: Mapped[str] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(String(300))
    body: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending|sent|failed|batched
    channels: Mapped[list] = mapped_column(default=list)
    dedupe_key: Mapped[str | None] = mapped_column(String(300), index=True)
    occurrences: Mapped[int] = mapped_column(default=1)
    video_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("videos.id"))
    is_incident: Mapped[bool] = mapped_column(Boolean, default=False)
    resolution: Mapped[str | None] = mapped_column(Text)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    acknowledged_by: Mapped[str | None] = mapped_column(String(200))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
