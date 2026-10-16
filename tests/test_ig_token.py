"""Weekly Instagram token renewal (waitwhy/publishing/tokens.py), with Instagram's endpoint mocked."""
import json

import httpx
import pytest

from waitwhy.models import Notification, SystemSetting
from waitwhy.publishing import tokens
from waitwhy.settings import secrets


@pytest.fixture(autouse=True)
def state_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("INSTAGRAM_ACCESS_TOKEN", "TOKEN-FROM-ENV")
    secrets.cache_clear()  # the app reads .env once at startup; tests change it
    yield tmp_path / "state"
    secrets.cache_clear()


def fake_get(status, body):
    def get(url, params=None, timeout=None):
        assert url == "https://graph.instagram.com/refresh_access_token"
        assert params["grant_type"] == "ig_refresh_token"
        fake_get.sent = params["access_token"]
        return httpx.Response(status, json=body)
    return get


def test_renews_and_uses_the_new_token(session, monkeypatch, state_dir):
    monkeypatch.setattr(tokens.httpx, "get", fake_get(200, {"access_token": "NEW-1", "expires_in": 5184000}))
    out = tokens.refresh_instagram(session)
    assert out == {"refreshed": True, "days_left": 60}
    assert fake_get.sent == "TOKEN-FROM-ENV"
    assert tokens.current_token() == "NEW-1"
    f = state_dir / "instagram_token.json"
    assert oct(f.stat().st_mode & 0o777) == "0o600"
    # the next renewal starts from the stored token, not the .env one
    monkeypatch.setattr(tokens.httpx, "get", fake_get(200, {"access_token": "NEW-2", "expires_in": 5184000}))
    tokens.refresh_instagram(session)
    assert fake_get.sent == "NEW-1" and tokens.current_token() == "NEW-2"


def test_token_never_lands_in_the_database(session, monkeypatch):
    monkeypatch.setattr(tokens.httpx, "get", fake_get(200, {"access_token": "SECRET", "expires_in": 5184000}))
    tokens.refresh_instagram(session)
    session.flush()
    stored = json.dumps([r.value for r in session.query(SystemSetting).all()])
    assert "SECRET" not in stored and "TOKEN-FROM-ENV" not in stored
    assert session.get(SystemSetting, tokens.STATUS_KEY).value["days_left"] == 60


def test_failure_alerts_the_owner_and_keeps_the_old_token(session, monkeypatch):
    monkeypatch.setattr(tokens.httpx, "get", fake_get(400, {"error": {"message": "Session has expired"}}))
    out = tokens.refresh_instagram(session)
    assert out["refreshed"] is False and "Session has expired" in out["error"]
    assert tokens.current_token() == "TOKEN-FROM-ENV"
    n = session.query(Notification).one()
    assert n.severity == "high" and "could not be renewed" in n.title


def test_skips_when_instagram_is_not_connected(session, monkeypatch):
    monkeypatch.setenv("INSTAGRAM_ACCESS_TOKEN", "")
    secrets.cache_clear()
    assert tokens.refresh_instagram(session) == {"skipped": "no Instagram token configured"}
