"""Keep the Instagram access token alive.

An Instagram long-lived token (Instagram API with Instagram Login) lasts about 60 days. Calling the
refresh endpoint while it is still valid, and at least 24 hours old, extends it to a fresh 60 days.
The token the owner puts in .env is the starting point. Each renewed token is written to a private
file (``$STATE_DIR/instagram_token.json``, mode 600, under the git-ignored ``data/`` by default) and
used from then on, so .env never needs editing again.

The token is never stored in the database: the dashboard's Settings page displays every stored
setting. Only the expiry date goes there (``instagram_token_status``). Runs weekly. If a renewal
fails, the owner gets an alert while there is still time to act.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
from sqlalchemy.orm import Session

from waitwhy.models import SystemSetting
from waitwhy.notify import alert
from waitwhy.settings import ROOT, secrets

STATUS_KEY = "instagram_token_status"
WARN_DAYS = 14


def _state_file() -> Path:
    return Path(os.environ.get("STATE_DIR") or ROOT / "data" / "state") / "instagram_token.json"


def current_token() -> str:
    """The newest token: the renewed one if there is one, else the one from .env."""
    f = _state_file()
    if f.exists():
        try:
            tok = json.loads(f.read_text()).get("token")
            if tok:
                return tok
        except (OSError, ValueError):
            pass
    return secrets().instagram_access_token


def _save(token: str) -> None:
    f = _state_file()
    f.parent.mkdir(parents=True, exist_ok=True)
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps({"token": token}))
    os.chmod(tmp, 0o600)
    tmp.replace(f)


def _set_status(session: Session, value: dict) -> None:
    row = session.get(SystemSetting, STATUS_KEY)
    if row:
        row.value, row.updated_by = value, "agent:publisher"
    else:
        session.add(SystemSetting(key=STATUS_KEY, value=value, updated_by="agent:publisher"))


def refresh_instagram(session: Session, host: str | None = None) -> dict:
    token = current_token()
    if not token:
        return {"skipped": "no Instagram token configured"}
    host = host or secrets().instagram_graph_host or "graph.instagram.com"
    now = datetime.now(timezone.utc)
    try:
        r = httpx.get(f"https://{host}/refresh_access_token",
                      params={"grant_type": "ig_refresh_token", "access_token": token}, timeout=30)
        try:
            body = r.json()
        except ValueError:
            body = {}
        if r.status_code != 200 or "access_token" not in body:
            err = body.get("error", {}) if isinstance(body, dict) else {}
            raise RuntimeError(f"HTTP {r.status_code}: {str(err.get('message', err) or r.text)[:300]}")
    except Exception as exc:  # noqa: BLE001 - any failure must reach the owner
        row = session.get(SystemSetting, STATUS_KEY)
        expires = (row.value or {}).get("expires_at") if row and row.value else None
        days_left = (datetime.fromisoformat(expires) - now).days if expires else None
        alert(session, "high", "publishing", "Instagram token could not be renewed",
              f"{exc}. Days left on the current token: {days_left if days_left is not None else 'unknown'}. "
              "Generate a new token in the Meta app (API setup with Instagram login), put it in .env as "
              "INSTAGRAM_ACCESS_TOKEN, delete data/state/instagram_token.json, and restart the app.",
              dedupe_key=f"ig-refresh:{now.date().isoformat()}")
        return {"refreshed": False, "error": str(exc)[:300], "days_left": days_left}
    _save(body["access_token"])
    expires_at = now + timedelta(seconds=int(body.get("expires_in", 0)))
    days_left = (expires_at - now).days
    _set_status(session, {"refreshed_at": now.isoformat(), "expires_at": expires_at.isoformat(),
                          "days_left": days_left})
    if days_left < WARN_DAYS:
        alert(session, "high", "publishing", "Instagram token expires soon",
              f"Renewed, but it only runs for {days_left} more days.", dedupe_key=f"ig-expiry:{expires_at.date()}")
    return {"refreshed": True, "days_left": days_left}
