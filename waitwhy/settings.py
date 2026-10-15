"""Configuration.

Two layers, deliberately separated:

* ``Secrets`` - credentials and deployment wiring, read ONLY from environment variables
  (populate them from a secret manager in production). Never stored in the database or YAML.
* ``company config`` - non-secret business settings from ``config/company.yaml``, deep-merged
  with runtime overrides stored in the ``system_settings`` table (edited from the dashboard).
"""
from __future__ import annotations

import copy
import functools
import os
from pathlib import Path
from typing import Any

import yaml
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parent.parent


class Secrets(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "development"
    database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5432/waitwhy"
    company_config_path: str = str(ROOT / "config" / "company.yaml")
    secret_key: str = "change-me"
    dashboard_username: str = "ceo"
    dashboard_password: str = ""          # empty => dashboard refuses to start in production
    public_base_url: str = "http://localhost:8000"

    # storage
    storage_local_root: str = str(ROOT / "data" / "media")
    s3_bucket: str = ""
    s3_endpoint_url: str = ""
    s3_region: str = "auto"
    s3_access_key_id: str = ""
    s3_secret_access_key: str = ""
    s3_public_base_url: str = ""          # optional CDN base for platform pulls (Instagram video_url)

    # AI providers
    anthropic_api_key: str = ""
    elevenlabs_api_key: str = ""
    elevenlabs_voice_id: str = ""
    higgsfield_api_key: str = ""
    higgsfield_api_secret: str = ""
    higgsfield_base_url: str = "https://api.higgsfield.ai"
    heygen_api_key: str = ""
    piper_voice_path: str = ""            # dev-only local TTS model (.onnx)

    # platforms
    youtube_client_id: str = ""
    youtube_client_secret: str = ""
    youtube_refresh_token: str = ""
    meta_page_id: str = ""
    meta_page_access_token: str = ""
    instagram_user_id: str = ""
    instagram_access_token: str = ""
    instagram_graph_host: str = "graph.instagram.com"   # or graph.facebook.com for FB-login tokens
    tiktok_client_key: str = ""
    tiktok_client_secret: str = ""
    tiktok_access_token: str = ""
    tiktok_app_audited: bool = False

    # notifications
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    notify_email_to: str = ""
    notify_email_from: str = ""
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    notify_webhook_url: str = ""

    backup_dir: str = str(ROOT / "backups")


@functools.lru_cache
def secrets() -> Secrets:
    return Secrets()


def _deep_merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


@functools.lru_cache
def _yaml_config(path: str) -> dict:
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def load_company_config(overrides: dict[str, Any] | None = None) -> dict:
    cfg = _yaml_config(os.environ.get("COMPANY_CONFIG_PATH", secrets().company_config_path))
    if overrides:
        cfg = _deep_merge(cfg, overrides)
    # Invariants that cannot be configured away.
    if cfg.get("operating_mode") == "supervised":
        cfg["content_approval_required"] = True
        cfg["auto_publish_enabled"] = False
    return cfg


def get_config(session=None) -> dict:
    """Effective config = YAML + DB overrides (if a session is given)."""
    if session is None:
        return load_company_config()
    from waitwhy.models import SystemSetting

    overrides: dict[str, Any] = {}
    for row in session.query(SystemSetting).all():
        overrides[row.key] = row.value
    return load_company_config(overrides)
