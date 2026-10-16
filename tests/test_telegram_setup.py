"""scripts/telegram_setup.py: finding the chat and saving the keys, with Telegram mocked."""
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("telegram_setup", ROOT / "scripts" / "telegram_setup.py")
ts = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ts)


def test_picks_the_newest_private_chat():
    ups = [{"update_id": 1, "message": {"chat": {"id": 11, "type": "private"}}},
           {"update_id": 2, "message": {"chat": {"id": -5, "type": "group"}}},
           {"update_id": 3, "my_chat_member": {}}]
    assert ts.private_chat_id(ups) == 11
    assert ts.private_chat_id([]) is None


def test_saves_keys_sends_test_and_never_prints_token(tmp_path, monkeypatch, capsys):
    env = tmp_path / ".env"
    env.write_text("APP_ENV=production\nTELEGRAM_CHAT_ID=\n")
    token = "123456:SECRET-token"
    monkeypatch.setattr(ts.getpass, "getpass", lambda prompt: token)
    sent = []

    def call(tok, method, payload=None):
        assert tok == token
        sent.append(method)
        if method == "getMe":
            return {"result": {"username": "whyinclay_alerts_bot"}}
        if method == "getUpdates":
            return {"result": [{"update_id": 7, "message": {"chat": {"id": 4242, "type": "private"}}}]}
        return {"result": {}}
    monkeypatch.setattr(ts, "call", call)
    monkeypatch.setattr(ts, "restart_services", lambda: None)
    ts.main(env_path=env, wait_s=5)
    text = env.read_text()
    assert f"TELEGRAM_BOT_TOKEN={token}" in text and "TELEGRAM_CHAT_ID=4242" in text
    assert "APP_ENV=production" in text and text.count("TELEGRAM_CHAT_ID") == 1
    assert sent == ["getMe", "getUpdates", "sendMessage"]
    assert oct(env.stat().st_mode)[-3:] == "600"
    assert token not in capsys.readouterr().out
