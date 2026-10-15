"""Financial reporting helpers (costs per video, revenue by status, pipeline summaries)."""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from waitwhy.business.budget import month_key
from waitwhy.models import Expense, ProviderUsage, RevenueTransaction, Sponsor, Video


def video_cost(session: Session, video_id, include_mock: bool = False) -> float:
    q = select(func.coalesce(func.sum(ProviderUsage.cost_usd), 0)).where(ProviderUsage.video_id == video_id)
    if not include_mock:
        q = q.where(ProviderUsage.is_mock.is_(False))
    direct = float(session.execute(q).scalar() or 0)
    exp = float(session.execute(select(func.coalesce(func.sum(Expense.amount_usd), 0))
                                .where(Expense.video_id == video_id)).scalar() or 0)
    return round(direct + exp, 2)


def avg_cost_per_published_video(session: Session) -> float | None:
    from waitwhy.models import PlatformPost
    vids = session.execute(select(PlatformPost.video_id).where(PlatformPost.is_public.is_(True),
                                                               PlatformPost.is_mock.is_(False)).distinct()).scalars().all()
    if not vids:
        return None
    return round(sum(video_cost(session, v) for v in vids) / len(vids), 2)


def spend_by_provider(session: Session, month: str | None = None, include_mock: bool = True) -> list[dict]:
    month = month or month_key()
    q = select(ProviderUsage.provider, ProviderUsage.is_mock, func.sum(ProviderUsage.cost_usd)).where(
        ProviderUsage.month == month).group_by(ProviderUsage.provider, ProviderUsage.is_mock)
    rows = [{"provider": p, "simulated": bool(mk), "usd": round(float(c or 0), 2)} for p, mk, c in session.execute(q)]
    return [r for r in rows if include_mock or not r["simulated"]]


def revenue_mtd(session: Session, status: str = "received") -> float:
    today = date.today()
    start = today.replace(day=1)
    col = RevenueTransaction.received_on if status == "received" else RevenueTransaction.invoiced_on
    q = select(func.coalesce(func.sum(RevenueTransaction.amount_usd), 0)).where(
        RevenueTransaction.status == status, col >= start)
    return round(float(session.execute(q).scalar() or 0), 2)


def outstanding_invoices(session: Session) -> list[RevenueTransaction]:
    return list(session.execute(select(RevenueTransaction).where(RevenueTransaction.status == "invoiced")
                                .order_by(RevenueTransaction.due_on)).scalars())


def monthly_pnl(session: Session, months: int = 6) -> list[dict]:
    out = defaultdict(lambda: {"expenses": 0.0, "usage_real": 0.0, "usage_simulated": 0.0, "revenue_received": 0.0})
    for m_, mk, c in session.execute(select(ProviderUsage.month, ProviderUsage.is_mock, func.sum(ProviderUsage.cost_usd))
                                     .group_by(ProviderUsage.month, ProviderUsage.is_mock)):
        out[m_]["usage_simulated" if mk else "usage_real"] += float(c or 0)
    for m_, c in session.execute(select(Expense.month, func.sum(Expense.amount_usd)).group_by(Expense.month)):
        out[m_]["expenses"] += float(c or 0)
    for r in session.execute(select(RevenueTransaction).where(RevenueTransaction.status == "received")).scalars():
        if r.received_on:
            out[month_key(r.received_on)]["revenue_received"] += float(r.amount_usd)
    rows = []
    for m_ in sorted(out)[-months:]:
        d = out[m_]
        cost = d["expenses"] + d["usage_real"]
        rows.append({"month": m_, **{k: round(v, 2) for k, v in d.items()},
                     "cash_contribution": round(d["revenue_received"] - cost, 2)})
    return rows


def sponsor_pipeline_summary(session: Session) -> str:
    rows = dict(session.execute(select(Sponsor.status, func.count()).group_by(Sponsor.status)).all())
    return ", ".join(f"{k}: {v}" for k, v in rows.items()) or "empty"


def record_expense(session: Session, *, vendor: str, category: str, amount_usd: float, kind: str = "cash",
                   is_fixed: bool = False, description: str = "", when: date | None = None, video_id=None) -> Expense:
    when = when or datetime.now(timezone.utc).date()
    e = Expense(incurred_on=when, month=month_key(when), category=category, vendor=vendor, description=description,
                amount_usd=amount_usd, kind=kind, is_fixed=is_fixed, video_id=video_id)
    session.add(e)
    session.flush()
    return e
