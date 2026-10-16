"""Connect the Why in Clay YouTube channel: get a refresh token and write it into .env.

Run on the machine that runs the app, with the OAuth client file downloaded from Google Cloud
(client type "Desktop app"):

    python3 scripts/youtube_auth.py ~/Downloads/client_secret_XXXX.json

It opens a browser for you to sign in. Choose the Google account and then the **Why in Clay**
channel. It receives the code on a local port and exchanges it for a refresh token. Then it checks
which channel the token belongs to and writes YOUTUBE_CLIENT_ID, YOUTUBE_CLIENT_SECRET and
YOUTUBE_REFRESH_TOKEN into .env. Secrets are never printed. Standard library only.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import http.server
import json
import os
import secrets
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from pathlib import Path

SCOPES = ["https://www.googleapis.com/auth/youtube.upload",
          "https://www.googleapis.com/auth/youtube.readonly",
          "https://www.googleapis.com/auth/yt-analytics.readonly"]
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
CHANNELS_URL = "https://www.googleapis.com/youtube/v3/channels?part=snippet&mine=true"
ROOT = Path(__file__).resolve().parent.parent


def load_client(path: Path) -> tuple[str, str]:
    data = json.loads(path.read_text())
    c = data.get("installed") or data.get("web")
    if not c:
        raise SystemExit("Not an OAuth client file: expected an 'installed' (Desktop app) section.")
    if "installed" not in data:
        print("Warning: this is a 'Web application' client; create a 'Desktop app' client if sign-in fails.")
    return c["client_id"], c["client_secret"]


def update_env(env_path: Path, values: dict[str, str]) -> None:
    """Set KEY=value lines in .env, replacing existing keys and appending missing ones."""
    lines = env_path.read_text().splitlines() if env_path.exists() else []
    seen = set()
    out = []
    for line in lines:
        key = line.split("=", 1)[0].strip()
        if key in values and not line.lstrip().startswith("#"):
            out.append(f"{key}={values[key]}")
            seen.add(key)
        else:
            out.append(line)
    out += [f"{k}={v}" for k, v in values.items() if k not in seen]
    env_path.write_text("\n".join(out) + "\n")
    os.chmod(env_path, 0o600)


def post_form(url: str, fields: dict) -> dict:
    req = urllib.request.Request(url, data=urllib.parse.urlencode(fields).encode(), method="POST",
                                 headers={"Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        raise SystemExit(f"Google refused the token exchange ({e.code}): {e.read().decode()[:300]}")


def wait_for_code(state: str):
    """Serve one loopback request; returns (result dict, port, thread, server)."""
    result: dict[str, str] = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            if q.get("state", [""])[0] != state:
                self.send_response(400)
                self.end_headers()
                return
            result["code"] = q.get("code", [""])[0]
            result["error"] = q.get("error", [""])[0]
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            msg = "Signed in. You can close this tab and go back to Terminal." if result["code"] else \
                f"Sign-in failed: {result['error']}"
            self.wfile.write(f"<p style='font:18px sans-serif'>{msg}</p>".encode())

        def log_message(self, *a):
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    port = server.server_address[1]
    t = threading.Thread(target=lambda: server.handle_request(), daemon=True)
    t.start()
    return result, port, t, server


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("client_file", type=Path)
    ap.add_argument("--env", type=Path, default=ROOT / ".env")
    args = ap.parse_args()
    client_id, client_secret = load_client(args.client_file.expanduser())

    state = secrets.token_urlsafe(16)
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    result, port, thread, server = wait_for_code(state)
    redirect = f"http://127.0.0.1:{port}"
    url = AUTH_URL + "?" + urllib.parse.urlencode({
        "client_id": client_id, "redirect_uri": redirect, "response_type": "code", "scope": " ".join(SCOPES),
        "access_type": "offline", "prompt": "select_account consent", "state": state,
        "code_challenge": challenge, "code_challenge_method": "S256"})
    print("Opening your browser. Pick your Google account, then the Why in Clay channel.")
    print("If it doesn't open, paste this address into the browser:\n" + url + "\n")
    webbrowser.open(url)
    thread.join(timeout=600)
    server.server_close()
    if not result.get("code"):
        raise SystemExit(f"No sign-in received ({result.get('error') or 'timed out after 10 minutes'}).")

    tok = post_form(TOKEN_URL, {"code": result["code"], "client_id": client_id, "client_secret": client_secret,
                                "redirect_uri": redirect, "grant_type": "authorization_code",
                                "code_verifier": verifier})
    refresh = tok.get("refresh_token")
    if not refresh:
        raise SystemExit("Google returned no refresh token. Remove the app's access at "
                         "https://myaccount.google.com/permissions and run this again.")
    granted = set(tok.get("scope", "").split())
    missing = [s.rsplit("/", 1)[-1] for s in SCOPES if s not in granted]
    if missing:
        print(f"Warning: these permissions were not granted: {missing}. Tick every box on the consent screen.")

    req = urllib.request.Request(CHANNELS_URL, headers={"Authorization": f"Bearer {tok['access_token']}"})
    with urllib.request.urlopen(req, timeout=30) as r:
        items = json.loads(r.read()).get("items", [])
    if not items:
        raise SystemExit("Signed in, but this account has no YouTube channel. Run again and pick the "
                         "Why in Clay channel (brand account) on the account chooser.")
    title = items[0]["snippet"]["title"]
    print(f"Connected to the YouTube channel: {title}")
    if "clay" not in title.lower():
        print("Warning: that doesn't look like the Why in Clay channel. Run again and pick the right one "
              "if needed; nothing is posted until dry-run is off.")

    update_env(args.env, {"YOUTUBE_CLIENT_ID": client_id, "YOUTUBE_CLIENT_SECRET": client_secret,
                          "YOUTUBE_REFRESH_TOKEN": refresh})
    print(f"Saved the YouTube keys to {args.env}. Restart the app's services so they pick them up.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
