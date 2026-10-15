"""Alerts and notifications (log, email, Telegram, generic webhook).

Rules: incidents are never concealed; duplicates are collapsed (occurrence counter) instead of
spamming; low-severity items are batched into the daily report rather than pushed.
"""
from __future__ import annotations

import logging
import smtplib
import uuid
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from waitwhy.models import Notification
from waitwhy.settings import get_config, secrets

log = logging.getLogger("waitwhy.notify")
SEVERITY_RANK = {"info": 0, "low": 1, "high": 2, "critical": 3}


def alert(
    session: Session,
    severity: str,
    category: str,
    title: str,
    body: str = "",
    *,
    dedupe_key: str | None = None,
    video_id: uuid.UUID | None = None,
    incident: bool | None = None,
    push: bool = True,
) -> Notification:
    now = datetime.now(timezone.utc)
    if dedupe_key:
        existing = session.execute(
            select(Notification).where(
                Notification.dedupe_key == dedupe_key,
                Notification.acknowledged_at.is_(None),
                Notification.created_at > now - timedelta(hours=24),
            )
        ).scalars().first()
        if existing:
            existing.occurrences += 1
            existing.body = body or existing.body
            session.flush()
            return existing
    n = Notification(
        severity=severity, category=category, title=title[:300], body=body, dedupe_key=dedupe_key,
        video_id=video_id, is_incident=incident if incident is not None else severity in ("critical", "high"),
        status="pending",
    )
    session.add(n)
    session.flush()
    cfg = get_config(session)
    threshold = SEVERITY_RANK.get(cfg.get("notifications", {}).get("min_severity_push", "high"), 2)
    if push and SEVERITY_RANK.get(severity, 0) >= threshold:
        dispatch(session, n, cfg)
    else:
        n.status = "batched"
    return n


def dispatch(session: Session, n: Notification, cfg: dict | None = None) -> None:
    cfg = cfg or get_config(session)
    channels = cfg.get("notifications", {}).get("channels", ["log"])
    sent, errors = [], []
    for ch in channels:
        try:
            send(ch, f"[{n.severity.upper()}] {n.title}", n.body)
            sent.append(ch)
        except Exception as exc:  # a broken channel must not break the pipeline
            errors.append(f"{ch}: {exc}")
            log.error("notification channel %s failed: %s", ch, exc)
    n.channels = sent
    n.status = "sent" if sent else "failed"
    n.sent_at = datetime.now(timezone.utc) if sent else None
    if errors:
        n.body = (n.body or "") + "\n\n[delivery errors] " + "; ".join(errors)


def send(channel: str, subject: str, body: str) -> None:
    s = secrets()
    if channel == "log":
        log.warning("NOTIFY %s\n%s", subject, body)
    elif channel == "email":
        if not (s.smtp_host and s.notify_email_to):
            raise RuntimeError("SMTP not configured")
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = s.notify_email_from or s.smtp_username
        msg["To"] = s.notify_email_to
        msg.set_content(body)
        with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=30) as smtp:
            smtp.starttls()
            if s.smtp_username:
                smtp.login(s.smtp_username, s.smtp_password)
            smtp.send_message(msg)
    elif channel == "telegram":
        if not (s.telegram_bot_token and s.telegram_chat_id):
            raise RuntimeError("Telegram not configured")
        text = f"{subject}\n\n{body}"[:4000]
        r = httpx.post(f"https://api.telegram.org/bot{s.telegram_bot_token}/sendMessage",
                       json={"chat_id": s.telegram_chat_id, "text": text}, timeout=20)
        r.raise_for_status()
    elif channel == "webhook":
        if not s.notify_webhook_url:
            raise RuntimeError("webhook not configured")
        r = httpx.post(s.notify_webhook_url, json={"text": f"*{subject}*\n{body}"}, timeout=20)
        r.raise_for_status()
    else:
        raise ValueError(f"unknown channel {channel}")
