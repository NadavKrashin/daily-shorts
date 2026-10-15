"""Budget enforcement.

* Variable spend (provider usage + non-fixed expenses) is checked BEFORE every paid operation.
* Exceeding the monthly hard cap or the per-video ceiling raises ``BudgetExceeded``: the job parks as
  ``blocked``, already-generated work is kept, and a spending approval is requested.
* Alerts fire once per month at 50/80/95 % of the monthly operating budget.
* In dry-run mode simulated (mock) costs are counted too, so budget logic is exercised end-to-end;
  real costs are always counted and reported separately.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from waitwhy.errors import BudgetExceeded
from waitwhy.models import Approval, Expense, ProviderUsage, Video


def month_key(dt: datetime | date | None = None) -> str:
    dt = dt or datetime.now(timezone.utc)
    return f"{dt.year:04d}-{dt.month:02d}"


def _f(x) -> float:
    return float(x or 0)


def usage_spend(session: Session, month: str, include_mock: bool, video_id: uuid.UUID | None = None) -> float:
    q = select(func.coalesce(func.sum(ProviderUsage.cost_usd), 0)).where(ProviderUsage.month == month)
    if not include_mock:
        q = q.where(ProviderUsage.is_mock.is_(False))
    if video_id:
        q = select(func.coalesce(func.sum(ProviderUsage.cost_usd), 0)).where(ProviderUsage.video_id == video_id)
        if not include_mock:
            q = q.where(ProviderUsage.is_mock.is_(False))
    return _f(session.execute(q).scalar())


def expense_spend(session: Session, month: str, fixed: bool | None = None) -> float:
    q = select(func.coalesce(func.sum(Expense.amount_usd), 0)).where(Expense.month == month,
                                                                      Expense.kind.in_(["cash", "accrued"]))
    if fixed is not None:
        q = q.where(Expense.is_fixed.is_(fixed))
    return _f(session.execute(q).scalar())


def approved_extensions(session: Session, month: str, video_id: uuid.UUID | None = None) -> float:
    rows = session.execute(select(Approval).where(Approval.kind == "spending", Approval.status == "approved")).scalars()
    total = 0.0
    for a in rows:
        p = a.payload or {}
        if video_id is None and p.get("scope") == "monthly" and p.get("month") == month:
            total += float(p.get("amount_usd", 0))
        if video_id is not None and p.get("scope") == "video" and p.get("video_id") == str(video_id):
            total += float(p.get("amount_usd", 0))
    return total


def status(session: Session, cfg: dict, month: str | None = None) -> dict:
    month = month or month_key()
    include_mock = bool(cfg.get("dry_run_mode"))
    real_usage = usage_spend(session, month, include_mock=False)
    sim_usage = usage_spend(session, month, include_mock=True) - real_usage
    variable = real_usage + expense_spend(session, month, fixed=False) + (sim_usage if include_mock else 0)
    fixed = expense_spend(session, month, fixed=True)
    hard_cap = float(cfg["monthly_hard_cap_usd"]) + approved_extensions(session, month)
    budget = float(cfg["monthly_budget_usd"])
    return {
        "month": month,
        "variable_spend_usd": round(variable, 2),
        "fixed_spend_usd": round(fixed, 2),
        "total_spend_usd": round(variable + fixed, 2),
        "real_provider_usage_usd": round(real_usage, 2),
        "simulated_usage_usd": round(sim_usage, 2),
        "monthly_budget_usd": budget,
        "hard_cap_usd": hard_cap,
        "remaining_vs_budget_usd": round(budget - variable - fixed, 2),
        "remaining_vs_cap_usd": round(hard_cap - variable, 2),
        "pct_of_budget": round((variable + fixed) / budget, 3) if budget else None,
    }


def check(session: Session, cfg: dict, estimated_usd: float, what: str, video: Video | None = None) -> None:
    """Raise BudgetExceeded (and request approval) if this spend would break a limit."""
    if estimated_usd <= 0:
        return
    st = status(session, cfg)
    if st["variable_spend_usd"] + estimated_usd > st["hard_cap_usd"]:
        _request_spending_approval(session, "monthly", st["month"], estimated_usd, what, video,
                                   f"Monthly variable cap ${st['hard_cap_usd']:.0f} would be exceeded "
                                   f"(spent ${st['variable_spend_usd']:.2f}, needs ${estimated_usd:.2f}).")
        raise BudgetExceeded(f"monthly hard cap reached while {what}", needed_usd=estimated_usd,
                             remaining_usd=st["remaining_vs_cap_usd"], scope="monthly")
    if video is not None:
        include_mock = bool(cfg.get("dry_run_mode"))
        spent = usage_spend(session, st["month"], include_mock, video_id=video.id)
        limit = float(video.budget_usd or cfg["max_cost_per_video_usd"]) + approved_extensions(session, st["month"], video.id)
        if spent + estimated_usd > limit:
            _request_spending_approval(session, "video", st["month"], estimated_usd, what, video,
                                       f"Video '{video.title}' would exceed its ${limit:.2f} ceiling "
                                       f"(spent ${spent:.2f}, next step ${estimated_usd:.2f}).")
            raise BudgetExceeded(f"per-video budget reached while {what}", needed_usd=estimated_usd,
                                 remaining_usd=limit - spent, scope="video")


def _request_spending_approval(session, scope, month, amount, what, video, reason) -> None:
    """Recorded in its OWN transaction: the caller's transaction is rolled back when the job parks,
    and the approval request + alert must survive that."""
    from waitwhy.db import session_factory
    from waitwhy.notify import alert

    vid = video.id if (video is not None and scope == "video") else None
    s2 = session_factory()()
    try:
        existing = s2.execute(select(Approval).where(Approval.kind == "spending", Approval.status == "pending",
                                                     Approval.video_id == vid if vid else Approval.video_id.is_(None))
                              ).scalars().first()
        if existing:
            return
        s2.add(Approval(kind="spending", status="pending", video_id=vid, reason=reason, target_type="budget",
                        target_id=scope, payload={"scope": scope, "month": month,
                                                  "video_id": str(video.id) if video is not None else None,
                                                  "amount_usd": round(max(amount * 3, 10.0), 2),
                                                  "blocked_operation": what}))
        alert(s2, "high", "budget", "Spending approval needed - expensive work paused", reason,
              dedupe_key=f"budget-block:{scope}:{month}:{vid or ''}")
        s2.commit()
    finally:
        s2.close()


def record_usage(session: Session, cfg: dict, *, provider: str, model: str | None, kind: str, cost_usd: float,
                 video_id: uuid.UUID | None = None, units: dict | None = None, is_mock: bool = False,
                 is_estimate: bool = True, agent_run_id=None, asset_id=None) -> ProviderUsage:
    row = ProviderUsage(provider=provider, model=model, kind=kind, cost_usd=Decimal(str(round(cost_usd, 4))),
                        video_id=video_id, units=units or {}, is_mock=is_mock, is_estimate=is_estimate,
                        agent_run_id=agent_run_id, asset_id=asset_id, month=month_key())
    session.add(row)
    session.flush()
    _threshold_alerts(session, cfg)
    return row


def _threshold_alerts(session: Session, cfg: dict) -> None:
    from waitwhy.notify import alert

    st = status(session, cfg)
    pct = st["pct_of_budget"] or 0
    for th in sorted(cfg.get("budget_alert_thresholds", [0.5, 0.8, 0.95])):
        if pct >= th:
            sev = "high" if th >= 0.8 else "low"
            alert(session, sev, "budget", f"Budget {int(th * 100)}% reached for {st['month']}",
                  f"Spent ${st['total_spend_usd']:.2f} of ${st['monthly_budget_usd']:.0f} "
                  f"(hard cap ${st['hard_cap_usd']:.0f}).", dedupe_key=f"budget-threshold:{st['month']}:{th}")
    if st["variable_spend_usd"] > st["hard_cap_usd"]:
        alert(session, "critical", "budget", "Monthly hard cap EXCEEDED",
              f"Variable spend ${st['variable_spend_usd']:.2f} > cap ${st['hard_cap_usd']:.2f}",
              dedupe_key=f"budget-exceeded:{st['month']}")
