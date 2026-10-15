"""Builds provider instances from config + secrets. dry_run_mode forces mock paid generators."""
from __future__ import annotations

import functools

from waitwhy.settings import secrets


def llm(cfg: dict):
    s = secrets()
    if cfg["providers"].get("llm") == "anthropic" and s.anthropic_api_key:
        from waitwhy.providers.llm_anthropic import AnthropicLLM
        return AnthropicLLM(s.anthropic_api_key)
    from waitwhy.providers.llm_mock import MockLLM
    return MockLLM()


@functools.lru_cache(maxsize=4)
def _piper(path: str):
    from waitwhy.providers.tts import PiperTTS
    return PiperTTS(path)


def tts(cfg: dict):
    s = secrets()
    choice = cfg["providers"].get("tts")
    if choice == "elevenlabs" and s.elevenlabs_api_key and s.elevenlabs_voice_id and not cfg.get("dry_run_mode"):
        from waitwhy.providers.tts import ElevenLabsTTS
        return ElevenLabsTTS(s.elevenlabs_api_key, s.elevenlabs_voice_id, cfg.get("elevenlabs", {}))
    if s.piper_voice_path and choice in ("piper", "elevenlabs"):
        # Dev fallback: real speech for previews, flagged non-commercial so QC blocks publishing.
        return _piper(s.piper_voice_path)
    from waitwhy.providers.tts import MockTTS
    return MockTTS()


def mediagen(cfg: dict):
    s = secrets()
    v = cfg["video"]
    if cfg["providers"].get("video") == "higgsfield" and s.higgsfield_api_key and not cfg.get("dry_run_mode"):
        from waitwhy.providers.mediagen import HiggsfieldAPI
        return HiggsfieldAPI(s.higgsfield_api_key, s.higgsfield_api_secret, cfg.get("higgsfield", {}),
                             s.higgsfield_base_url)
    from waitwhy.providers.mediagen import MockMediaGen
    return MockMediaGen(v["width"], v["height"])


@functools.lru_cache(maxsize=2)
def _storage(kind: str):
    s = secrets()
    if kind == "s3":
        from waitwhy.providers.storage import S3Storage
        return S3Storage(s.s3_bucket, s.s3_endpoint_url, s.s3_region, s.s3_access_key_id, s.s3_secret_access_key,
                         s.s3_public_base_url)
    from waitwhy.providers.storage import LocalStorage
    return LocalStorage(s.storage_local_root, s.public_base_url if s.app_env == "production" else None)


def storage(cfg: dict | None = None):
    kind = (cfg or {}).get("providers", {}).get("storage", "local")
    return _storage(kind)
