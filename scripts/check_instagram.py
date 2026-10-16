"""Check that the app's Instagram access token works. Run on the Mac that runs the app:

    cd ~/daily-shorts && git pull && .venv/bin/python scripts/check_instagram.py

It uses the same token the app would use (the renewed copy in data/state/ if there is one, otherwise
INSTAGRAM_ACCESS_TOKEN from .env), asks Instagram which account it belongs to, and checks it matches
INSTAGRAM_USER_ID and can publish. It only reads; it never posts. The token is never printed.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx  # noqa: E402

from waitwhy.publishing.tokens import _state_file, current_token  # noqa: E402
from waitwhy.settings import load_company_config, secrets  # noqa: E402

FIX = ("Fix: Meta developer dashboard -> your app -> Instagram -> API setup with Instagram login -> "
       "Generate token for @whyinclay. Put it in ~/daily-shorts/.env as INSTAGRAM_ACCESS_TOKEN, delete "
       "data/state/instagram_token.json if it exists, restart the app's services, and run this again.")


def get(url: str, token: str, **params) -> tuple[int, dict]:
    try:
        r = httpx.get(url, params={**params, "access_token": token}, timeout=30)
    except httpx.HTTPError as e:  # the message could contain the URL (and token): print only the type
        raise SystemExit(f"Could not reach Instagram ({type(e).__name__}). Check the Mac's internet connection.")
    try:
        return r.status_code, r.json()
    except ValueError:
        return r.status_code, {}


def main() -> int:
    s = secrets()
    token = current_token()
    source = _state_file() if _state_file().exists() else ".env"
    if not token:
        print(f"No Instagram token found (looked in {source}).\n{FIX}")
        return 1
    ver = load_company_config().get("meta_graph_version", "v25.0")
    base = f"https://{s.instagram_graph_host}/{ver}"
    code, me = get(f"{base}/me", token, fields="user_id,username")
    if code != 200 or "username" not in me:
        err = (me.get("error") or {}).get("message", f"HTTP {code}")
        print(f"The token does NOT work. Instagram says: {err}\n(token from {source})\n{FIX}")
        return 1
    print(f"Token works: it belongs to @{me['username']} (token from {source}).")
    uid = str(me.get("user_id") or me.get("id") or "")
    if s.instagram_user_id and uid and uid != str(s.instagram_user_id):
        print(f"But INSTAGRAM_USER_ID in .env is {s.instagram_user_id}, while this token's account is {uid}. "
              f"Set INSTAGRAM_USER_ID={uid} in .env and restart the services.")
        return 1
    code, lim = get(f"{base}/{s.instagram_user_id or uid}/content_publishing_limit", token, fields="quota_usage,config")
    if code == 200 and lim.get("data"):
        d = lim["data"][0]
        total = (d.get("config") or {}).get("quota_total", "?")
        print(f"Publishing allowed: {d.get('quota_usage', 0)} of {total} posts used in the last 24 hours.")
    else:
        err = (lim.get("error") or {}).get("message", f"HTTP {code}")
        print(f"The account checks out, but Instagram refused the publishing check: {err}\n{FIX}")
        return 1
    print("All good: the app can post to Instagram.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
