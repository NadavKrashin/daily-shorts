"""Finance and commercial operations."""
from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, IdMixin, TimestampMixin


class Expense(IdMixin, TimestampMixin, Base):
    __tablename__ = "expenses"
    incurred_on: Mapped[date] = mapped_column(Date, index=True)
    month: Mapped[str] = mapped_column(String(7), index=True)
    category: Mapped[str] = mapped_column(String(64))
    # ai_llm | video_generation | voiceover | audio_licensing | hosting | storage | software | freelance | other
    vendor: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    amount_usd: Mapped[float] = mapped_column(Numeric(12, 2))
    kind: Mapped[str] = mapped_column(String(16), default="cash")  # cash | estimated | accrued
    is_fixed: Mapped[bool] = mapped_column(default=False)          # subscriptions/hosting vs variable
    video_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("videos.id", ondelete="SET NULL"))
    receipt_ref: Mapped[str | None] = mapped_column(String(300))


class RevenueTransaction(IdMixin, TimestampMixin, Base):
    __tablename__ = "revenue_transactions"
    source: Mapped[str] = mapped_column(String(32))  # sponsorship | affiliate | platform | licensing | client
    counterparty: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    amount_usd: Mapped[float] = mapped_column(Numeric(12, 2))
    status: Mapped[str] = mapped_column(String(16))  # expected | invoiced | received | cancelled
    invoice_ref: Mapped[str | None] = mapped_column(String(200))
    invoiced_on: Mapped[date | None] = mapped_column(Date)
    due_on: Mapped[date | None] = mapped_column(Date)
    received_on: Mapped[date | None] = mapped_column(Date)
    deal_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("sponsorship_deals.id"))
    video_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("videos.id", ondelete="SET NULL"))
    is_client_work: Mapped[bool] = mapped_column(default=False)


class Sponsor(IdMixin, TimestampMixin, Base):
    __tablename__ = "sponsors"
    company: Mapped[str] = mapped_column(String(200), unique=True)
    website: Mapped[str | None] = mapped_column(String(300))
    product: Mapped[str | None] = mapped_column(String(300))
    sector: Mapped[str | None] = mapped_column(String(64))
    contact_info: Mapped[dict] = mapped_column(default=dict)
    contact_source: Mapped[str | None] = mapped_column(Text)  # where the contact came from (must be permitted)
    fit_reason: Mapped[str | None] = mapped_column(Text)
    video_concept: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), default="prospect")
    # prospect | drafted | approved_to_contact | contacted | negotiating | won | lost | do_not_contact
    est_deal_value_usd: Mapped[float | None] = mapped_column(Numeric(12, 2))
    contact_history: Mapped[list] = mapped_column(default=list)
    notes: Mapped[str | None] = mapped_column(Text)


class OutreachDraft(IdMixin, TimestampMixin, Base):
    __tablename__ = "outreach_drafts"
    sponsor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sponsors.id", ondelete="CASCADE"))
    subject: Mapped[str] = mapped_column(String(300))
    body: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default="draft")  # draft | approved | sent | rejected
    approval_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("approvals.id", use_alter=True))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SponsorshipDeal(IdMixin, TimestampMixin, Base):
    __tablename__ = "sponsorship_deals"
    sponsor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sponsors.id"))
    status: Mapped[str] = mapped_column(String(32), default="proposed")
    # proposed | negotiating | awaiting_approval | signed | delivered | paid | cancelled
    deliverables: Mapped[list] = mapped_column(default=list)
    usage_rights: Mapped[str | None] = mapped_column(Text)
    exclusivity: Mapped[str | None] = mapped_column(Text)
    value_usd: Mapped[float | None] = mapped_column(Numeric(12, 2))
    contract_ref: Mapped[str | None] = mapped_column(String(300))
    approval_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("approvals.id", use_alter=True))
