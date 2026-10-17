"""Access tokens must never reach the log files (httpx logs request URLs, which carry them)."""
import io
import logging

from waitwhy import cli


def test_tokens_are_masked_and_httpx_is_quiet():
    root = logging.getLogger()
    saved = root.handlers[:]
    buf = io.StringIO()
    root.handlers = [logging.StreamHandler(buf)]
    try:
        cli._setup_logging("INFO")
        logging.getLogger("waitwhy.test").warning(
            "POST https://graph.instagram.com/v25.0/1/media?access_token=IGAAsecret123&x=1 failed")
        logging.getLogger("waitwhy.test").warning("refresh %s", "refresh_token=1//abc client_secret=GOCSPX-zz")
        assert logging.getLogger("httpx").getEffectiveLevel() >= logging.WARNING
    finally:
        root.handlers = saved
    out = buf.getvalue()
    assert "IGAAsecret123" not in out and "1//abc" not in out and "GOCSPX-zz" not in out
    assert out.count("[redacted]") == 3 and "&x=1" in out
