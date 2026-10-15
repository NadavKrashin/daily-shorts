import os

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

URL = os.environ.get("MIGRATION_TEST_DATABASE_URL", "postgresql+psycopg://postgres@127.0.0.1:5432/waitwhy_mig")


def test_upgrade_downgrade_upgrade():
    eng = create_engine(URL)
    with eng.begin() as c:
        c.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public;"))
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", URL)
    command.upgrade(cfg, "head")
    tables = set(inspect(eng).get_table_names())
    for t in ["topics", "videos", "storyboard_scenes", "publication_jobs", "analytics_snapshots", "workflow_jobs",
              "provider_usage", "sponsorship_deals", "audit_logs", "system_settings", "experiments"]:
        assert t in tables
    command.downgrade(cfg, "base")
    assert set(inspect(eng).get_table_names()) <= {"alembic_version"}
    command.upgrade(cfg, "head")
    eng.dispose()
