"""Provider interfaces. Swap any vendor by implementing one of these and registering it in registry.py."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


@dataclass
class LLMResult:
    parsed: Any
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    is_mock: bool = False
    raw_text: str = ""


@dataclass
class SearchHit:
    url: str
    title: str
    page_age: str | None = None


@dataclass
class ResearchResult:
    memo: str
    hits: list[SearchHit]
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    searches: int = 0
    cost_usd: float = 0.0
    is_mock: bool = False


class LLMProvider(Protocol):
    name: str

    def structured(self, *, task: str, system: str, prompt: str, schema: type[T], model: str,
                   effort: str = "medium", max_tokens: int = 16000, context: dict | None = None,
                   images: list | None = None) -> LLMResult: ...

    def research(self, *, system: str, prompt: str, model: str, effort: str = "high",
                 max_searches: int = 8, context: dict | None = None) -> ResearchResult: ...


@dataclass
class SpeechResult:
    path: Path
    duration_s: float
    words: list[dict] = field(default_factory=list)  # [{"w": str, "s": float, "e": float}] relative to clip
    characters: int = 0
    cost_usd: float = 0.0
    voice_id: str | None = None
    voice_name: str | None = None
    rights: dict = field(default_factory=dict)
    is_mock: bool = False


class TTSProvider(Protocol):
    name: str

    def synthesize(self, text: str, out_path: Path, *, previous_text: str = "", next_text: str = "") -> SpeechResult: ...

    def estimate_cost(self, text: str) -> float: ...


@dataclass
class GenerationRequest:
    kind: str  # image | video
    prompt: str
    negative_prompt: str = ""
    duration_s: float = 5.0
    aspect_ratio: str = "9:16"
    seed: int | None = None
    reference_image_paths: list[Path] = field(default_factory=list)
    model: str | None = None


@dataclass
class GenerationResult:
    path: Path
    provider: str
    model: str
    external_id: str | None
    cost_usd: float
    seconds: float
    rights: dict
    is_mock: bool = False


class MediaGenProvider(Protocol):
    name: str

    def estimate_cost(self, req: GenerationRequest) -> float: ...

    def generate(self, req: GenerationRequest, out_path: Path) -> GenerationResult: ...


class Storage(Protocol):
    def put_file(self, local: Path, key: str, content_type: str | None = None) -> str: ...
    def get_file(self, key: str, local: Path) -> Path: ...
    def local_path(self, key: str) -> Path | None: ...
    def exists(self, key: str) -> bool: ...
    def public_url(self, key: str, expires_s: int = 3600) -> str | None: ...
    def health(self) -> bool: ...
