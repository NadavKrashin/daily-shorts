"""scripts/youtube_auth.py: the loopback sign-in flow and the .env update, with Google mocked."""
import importlib.util
import io
import json
import threading
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("youtube_auth", ROOT / "scripts" / "youtube_auth.py")
ya = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ya)


def test_update_env_replaces_and_appends(tmp_path):
    env = tmp_path / ".env"
    env.write_text("APP_ENV=production\nYOUTUBE_CLIENT_ID=\n# YOUTUBE_REFRESH_TOKEN=old comment\n")
    ya.update_env(env, {"YOUTUBE_CLIENT_ID": "cid", "YOUTUBE_REFRESH_TOKEN": "rt"})
    lines = env.read_text().splitlines()
    assert lines == ["APP_ENV=production", "YOUTUBE_CLIENT_ID=cid", "# YOUTUBE_REFRESH_TOKEN=old comment",
                     "YOUTUBE_REFRESH_TOKEN=rt"]
    assert oct(env.stat().st_mode & 0o777) == "0o600"


def test_full_flow_writes_keys_without_printing_them(tmp_path, monkeypatch, capsys):
    client = tmp_path / "client.json"
    client.write_text(json.dumps({"installed": {"client_id": "cid.apps", "client_secret": "csecret"}}))
    env = tmp_path / ".env"
    env.write_text("APP_ENV=production\n")
    real_urlopen = urllib.request.urlopen

    def fake_browser(url):  # Google redirects back to the loopback address with a code
        q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
        assert q["access_type"] == ["offline"] and q["code_challenge_method"] == ["S256"]
        back = f"{q['redirect_uri'][0]}/?code=abc&state={q['state'][0]}"
        threading.Thread(target=lambda: real_urlopen(back, timeout=5).read()).start()
        return True

    def fake_post(url, fields):
        assert fields["code"] == "abc" and fields["code_verifier"]
        return {"refresh_token": "SECRET-RT", "access_token": "at", "scope": " ".join(ya.SCOPES)}

    def fake_urlopen(req, timeout=30):
        assert req.full_url == ya.CHANNELS_URL
        return io.BytesIO(json.dumps({"items": [{"snippet": {"title": "Why in Clay"}}]}).encode())

    monkeypatch.setattr(ya.webbrowser, "open", fake_browser)
    monkeypatch.setattr(ya, "post_form", fake_post)
    monkeypatch.setattr(ya.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr("sys.argv", ["youtube_auth.py", str(client), "--env", str(env)])
    assert ya.main() == 0
    text = env.read_text()
    assert "YOUTUBE_REFRESH_TOKEN=SECRET-RT" in text and "YOUTUBE_CLIENT_SECRET=csecret" in text
    out = capsys.readouterr().out
    assert "Connected to the YouTube channel: Why in Clay" in out
    assert "SECRET-RT" not in out and "csecret" not in out
