"""Test setup: isolated Postgres database, mock providers, dry-run mode, temp storage. No paid APIs."""
import os
import tempfile

TEST_DB = os.environ.get("TEST_DATABASE_URL", "postgresql+psycopg://postgres@127.0.0.1:5432/waitwhy_test")
os.environ["DATABASE_URL"] = TEST_DB
os.environ["STORAGE_LOCAL_ROOT"] = tempfile.mkdtemp(prefix="ww-test-media-")
os.environ["BACKUP_DIR"] = tempfile.mkdtemp(prefix="ww-test-bak-")
for k in ("ANTHROPIC_API_KEY", "ELEVENLABS_API_KEY", "HIGGSFIELD_API_KEY", "YOUTUBE_REFRESH_TOKEN",
          "INSTAGRAM_ACCESS_TOKEN", "META_PAGE_ACCESS_TOKEN", "TIKTOK_ACCESS_TOKEN"):
    os.environ[k] = ""
os.environ["PIPER_VOICE_PATH"] = ""
os.environ["DASHBOARD_PASSWORD"] = "test-pass"

import pytest  # noqa: E402
from sqlalchemy import text  # noqa: E402

from waitwhy.db import get_engine, session_factory  # noqa: E402
from waitwhy.models import Base  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def schema():
    from alembic import command
    from alembic.config import Config
    eng = get_engine()
    with eng.begin() as c:
        c.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public;"))
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", TEST_DB)
    command.upgrade(cfg, "head")
    yield


@pytest.fixture(autouse=True)
def clean_db(schema):
    eng = get_engine()
    names = ", ".join(t.name for t in Base.metadata.sorted_tables)
    with eng.begin() as c:
        c.execute(text(f"TRUNCATE {names} CASCADE"))
    yield


@pytest.fixture
def session():
    s = session_factory()()
    yield s
    s.rollback()
    s.close()


@pytest.fixture
def cfg(session):
    from waitwhy.settings import get_config
    return get_config(session)


def set_setting(session, key, value):
    from waitwhy.models import SystemSetting
    row = session.get(SystemSetting, key)
    if row:
        row.value = value
    else:
        session.add(SystemSetting(key=key, value=value, updated_by="test"))
    session.commit()
