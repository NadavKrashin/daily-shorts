"""Versioned prompt templates (markdown + YAML front matter + Jinja2).

Each file: front matter (name, version, purpose) then ``## system`` and ``## user`` sections.
Bump ``version`` on every edit; the version is stored on every agent_run for traceability.
"""
from __future__ import annotations

import functools
from dataclasses import dataclass
from pathlib import Path

import yaml
from jinja2 import Environment, StrictUndefined

DIR = Path(__file__).parent
_env = Environment(undefined=StrictUndefined, trim_blocks=True, lstrip_blocks=True, autoescape=False)


@dataclass
class Prompt:
    name: str
    version: str
    system: str
    user: str


@functools.lru_cache
def _load(name: str) -> tuple[dict, str, str]:
    raw = (DIR / f"{name}.md").read_text(encoding="utf-8")
    _, fm, body = raw.split("---", 2)
    meta = yaml.safe_load(fm)
    sys_part, user_part = body.split("## user", 1)
    sys_part = sys_part.split("## system", 1)[1]
    return meta, sys_part.strip(), user_part.strip()


def render(name: str, **vars) -> Prompt:
    meta, system, user = _load(name)
    return Prompt(name=meta["name"], version=str(meta["version"]),
                  system=_env.from_string(system).render(**vars), user=_env.from_string(user).render(**vars))


def list_prompts() -> list[dict]:
    out = []
    for p in sorted(DIR.glob("*.md")):
        meta, _, _ = _load(p.stem)
        out.append(meta)
    return out
