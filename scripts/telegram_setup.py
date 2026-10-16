"""Send the app's alerts (such as "post this on TikTok now") to your phone through a Telegram bot.

Run on the Mac that runs the app:

    python3 scripts/telegram_setup.py

1. In Telegram, open @BotFather, send /newbot, and give it a name (e.g. "Why in Clay alerts").
   BotFather replies with a token.
2. Paste the token when this script asks (it is not shown on screen).
3. Open your new bot in Telegram and send it any message, e.g. "hi".

The script finds your chat, sends a test message, writes TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID
into .env (mode 600) and restarts the app's services so they pick it up. Secrets are never printed.
Standard library only.
"""
from __future__ import annotations

import getpass
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
API = "https://api.telegram.org/bot{token}/{method}"
SERVICES = ("api", "worker", "scheduler")


def call(token: str, method: str, payload: dict | None = None) -> dict:
    data = json.dumps(payload or {}).encode()
    req = urllib.request.Request(API.format(token=token, method=method), data=data,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=40) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        if e.code in (401, 404):
            raise SystemExit("Telegram rejected the token. Copy it again from @BotFather.")
        raise SystemExit(f"Telegram error {e.code}.")


def private_chat_id(updates: list[dict]) -> int | None:
    """The newest private chat that messaged the bot (groups and channels are ignored)."""
    for u in reversed(updates):
        chat = (u.get("message") or {}).get("chat") or {}
        if chat.get("type") == "private":
            return chat["id"]
    return None


def update_env(env_path: Path, values: dict[str, str]) -> None:
    """Set KEY=value lines in .env, replacing existing keys and appending missing ones."""
    lines = env_path.read_text().splitlines() if env_path.exists() else []
    seen, out = set(), []
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


def restart_services() -> None:
    if sys.platform != "darwin":
        print("Restart the app's services so they read the new .env.")
        return
    uid = os.getuid()
    for s in SERVICES:
        # launchd restarts the service (KeepAlive), which then re-reads .env.
        subprocess.run(["launchctl", "kill", "SIGTERM", f"gui/{uid}/co.whyinclay.{s}"], capture_output=True)
    print("Restarted the app's services.")


def main(env_path: Path = ROOT / ".env", wait_s: int = 180) -> None:
    token = getpass.getpass("Paste the bot token from @BotFather (hidden): ").strip()
    if ":" not in token:
        raise SystemExit("That doesn't look like a bot token (it has the form 123456:ABC...).")
    me = call(token, "getMe")["result"]
    print(f"Bot found: @{me['username']}. Now open it in Telegram and send it any message.")
    chat_id, deadline, offset = None, time.time() + wait_s, None
    while chat_id is None and time.time() < deadline:
        updates = call(token, "getUpdates", {"timeout": 25, **({"offset": offset} if offset else {})})["result"]
        chat_id = private_chat_id(updates)
        if updates:
            offset = updates[-1]["update_id"] + 1
    if chat_id is None:
        raise SystemExit("No message arrived. Send your bot a message in Telegram and run this again.")
    call(token, "sendMessage", {"chat_id": chat_id,
                                "text": "Why in Clay alerts are connected. You'll get a message here when a "
                                        "video needs posting on TikTok or something needs your attention."})
    update_env(env_path, {"TELEGRAM_BOT_TOKEN": token, "TELEGRAM_CHAT_ID": str(chat_id)})
    print(f"Sent a test message and saved the Telegram keys to {env_path}.")
    restart_services()


if __name__ == "__main__":
    main()
