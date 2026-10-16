"""scripts/check_instagram.py: reports whether the token works, never printing it (Instagram mocked)."""
import importlib.util
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("check_instagram", ROOT / "scripts" / "check_instagram.py")
ci = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ci)
TOKEN = "IGAAsecret-token"


class R:
    def __init__(self, code, body):
        self.status_code, self._b = code, body

    def json(self):
        return self._b


def _setup(monkeypatch, responses):
    monkeypatch.setattr(ci, "current_token", lambda: TOKEN)
    monkeypatch.setattr(ci, "_state_file", lambda: ROOT / "nonexistent" / "x.json")

    class S:
        instagram_graph_host, instagram_user_id = "graph.instagram.com", "17841"
    monkeypatch.setattr(ci, "secrets", lambda: S())

    def get(url, params, timeout):
        assert params["access_token"] == TOKEN
        return responses.pop(0)
    monkeypatch.setattr(ci.httpx, "get", get)


def test_working_token(monkeypatch, capsys):
    _setup(monkeypatch, [R(200, {"user_id": "17841", "username": "whyinclay"}),
                         R(200, {"data": [{"quota_usage": 0, "config": {"quota_total": 100}}]})])
    assert ci.main() == 0
    out = capsys.readouterr().out
    assert "@whyinclay" in out and "0 of 100" in out and TOKEN not in out


def test_dead_token(monkeypatch, capsys):
    _setup(monkeypatch, [R(400, {"error": {"message": "Error validating access token: session invalidated"}})])
    assert ci.main() == 1
    out = capsys.readouterr().out
    assert "does NOT work" in out and "session invalidated" in out and TOKEN not in out


def test_network_error_never_prints_url(monkeypatch, capsys):
    _setup(monkeypatch, [])

    def boom(url, params, timeout):
        raise httpx.ConnectError(f"failed {url}?access_token={params['access_token']}")
    monkeypatch.setattr(ci.httpx, "get", boom)
    try:
        ci.main()
    except SystemExit as e:
        assert TOKEN not in str(e) and "ConnectError" in str(e)
