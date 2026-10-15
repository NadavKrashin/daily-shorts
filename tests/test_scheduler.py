from datetime import datetime
from zoneinfo import ZoneInfo

from waitwhy.jobs import scheduler
from waitwhy.models import WorkflowJob

TZ = ZoneInfo("Asia/Jerusalem")


def test_cron_parsing():
    c = scheduler.Cron("30 8 * * *")
    assert c.matches(datetime(2026, 10, 15, 8, 30, tzinfo=TZ))
    assert not c.matches(datetime(2026, 10, 15, 8, 31, tzinfo=TZ))
    sunday = scheduler.Cron("0 10 * * 0")
    assert sunday.matches(datetime(2026, 10, 18, 10, 0, tzinfo=TZ))  # 2026-10-18 is a Sunday
    assert scheduler.Cron("*/5 * * * *").matches(datetime(2026, 1, 1, 0, 55))


def test_tick_is_idempotent_and_uses_owner_timezone(session):
    now = datetime(2026, 10, 15, 9, 0, 30, tzinfo=TZ)
    k1 = scheduler.tick(now)
    k2 = scheduler.tick(now)
    assert k1 == k2
    reports = session.query(WorkflowJob).filter_by(type="daily_report").all()
    assert len(reports) == 1
    assert "09:00:00+03:00" in reports[0].idempotency_key


def test_missed_slot_is_caught_up_once_after_downtime(session):
    # scheduler was down at 09:00; comes back at 11:40 -> the 09:00 report still runs, exactly once
    scheduler.tick(datetime(2026, 10, 15, 11, 40, tzinfo=TZ))
    scheduler.tick(datetime(2026, 10, 15, 11, 41, tzinfo=TZ))
    assert session.query(WorkflowJob).filter_by(type="daily_report").count() == 1
