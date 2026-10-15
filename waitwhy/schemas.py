"""Structured agent inputs/outputs (Pydantic). Agents talk ONLY through these contracts."""
from __future__ import annotations

import json
import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

Beat = Literal["hook", "mystery", "setup", "explanation", "reveal", "conclusion"]


# ---------------------------------------------------------------- topics
class TopicScores(BaseModel):
    hook_strength: int = Field(ge=0, le=100)
    visual_potential: int = Field(ge=0, le=100)
    audience_curiosity: int = Field(ge=0, le=100)
    scientific_clarity: int = Field(ge=0, le=100)
    evergreen: int = Field(ge=0, le=100)
    originality: int = Field(ge=0, le=100)
    feasibility: int = Field(ge=0, le=100)

    def weighted(self, weights: dict[str, float]) -> float:
        return round(sum(getattr(self, k) * w for k, w in weights.items()), 1)


class TopicCandidate(BaseModel):
    title: str
    category: str
    angle: str = Field(description="The specific surprising mechanism or reveal this video would explain")
    summary: str
    keywords: list[str]
    risk_flags: list[str] = Field(description="Any of: medical, legal, financial, safety, breaking_news; empty if none")
    scores: TopicScores
    reasoning: str


class TopicBatch(BaseModel):
    candidates: list[TopicCandidate]


# ---------------------------------------------------------------- research / fact-check
SourceType = Literal["peer_reviewed", "primary", "institution", "reference", "secondary"]


class Source(BaseModel):
    id: str = Field(description="Short id like S1")
    url: str
    title: str
    publisher: str
    source_type: SourceType
    accessed_on: str = Field(description="ISO date the source was accessed")
    key_excerpt: str = Field(description="Short paraphrase of what this source supports")


class Claim(BaseModel):
    id: str = Field(description="Short id like C1")
    text: str
    importance: Literal["central", "supporting"]
    status: Literal["verified", "partially_verified", "unverified", "false"]
    source_ids: list[str]
    notes: str = ""


class FactSheet(BaseModel):
    topic: str
    core_explanation: str
    claims: list[Claim]
    sources: list[Source]
    uncertainties: list[str]
    misleading_simplifications: list[str] = Field(description="Tempting but wrong framings the script must avoid")
    safe_analogies: list[str]
    risk_level: Literal["standard", "high"]
    risk_reasons: list[str]
    verdict: Literal["verified", "needs_research", "reject"]

    def independent_support(self, claim: Claim) -> int:
        pubs = {s.publisher.strip().lower() for s in self.sources if s.id in claim.source_ids}
        return len(pubs)


# ---------------------------------------------------------------- script
class ScriptSegment(BaseModel):
    beat: Beat
    text: str
    claim_ids: list[str] = Field(description="Fact-sheet claim ids this sentence relies on (empty if none)")
    visual_intent: str


class ScriptScores(BaseModel):
    clarity: int = Field(ge=0, le=100)
    originality: int = Field(ge=0, le=100)
    accuracy: int = Field(ge=0, le=100)
    pacing: int = Field(ge=0, le=100)
    hook_strength: int = Field(ge=0, le=100)


class ScriptDraft(BaseModel):
    title: str
    alt_hooks: list[str] = Field(description="Exactly three alternative opening hooks")
    chosen_hook_index: int
    hook_style: str = Field(description="e.g. paradox, question, bold_claim, visual_shock, everyday_moment")
    story_structure: str = Field(description="e.g. hook-mystery-setup-explain-reveal-conclude")
    segments: list[ScriptSegment]
    conclusion: str
    why_compelling: str
    scores: ScriptScores

    @property
    def full_text(self) -> str:
        return " ".join(s.text.strip() for s in self.segments)

    @property
    def word_count(self) -> int:
        return len(re.findall(r"[A-Za-z0-9'’%-]+", self.full_text))

    @property
    def claim_ids(self) -> set[str]:
        return {c for s in self.segments for c in s.claim_ids}

    def estimated_duration_s(self, wpm: float = 150.0) -> float:
        return round(self.word_count / wpm * 60.0, 1)


# ---------------------------------------------------------------- storyboard
class Param(BaseModel):
    key: str
    value: str = Field(description="JSON-encoded value or plain string")


class ColorRole(BaseModel):
    role: str
    hex: str


class StyleSpec(BaseModel):
    look: str
    lighting: str
    palette: list[ColorRole]
    camera_geography: str = Field(description="Fixed spatial rules, e.g. 'traffic always flows left to right'")
    typography: str


class RecurringObject(BaseModel):
    id: str
    description: str
    canonical_color: str
    reference_prompt: str


class SceneSpec(BaseModel):
    scene_number: int
    beat: Beat
    narration: str
    start_s: float
    end_s: float
    visual_description: str
    camera_angle: str
    camera_movement: str
    main_objects: list[str]
    behavior: str
    color_direction: str
    animation_motion: str
    on_screen_text: str = ""
    sound_effects: list[str]
    transition: Literal["cut", "crossfade", "zoom", "slide"]
    render_method: Literal["programmatic", "ai_image", "ai_video"]
    template: str = Field(description="Programmatic template id (required when render_method=programmatic)")
    template_params: list[Param] = []
    generation_prompt: str = ""
    negative_prompt: str = ""
    continuity: list[str]
    input_assets: list[str] = []
    output_assets: list[str] = []

    def params(self) -> dict:
        out = {}
        for p in self.template_params:
            try:
                out[p.key] = json.loads(p.value)
            except (json.JSONDecodeError, TypeError):
                out[p.key] = p.value
        return out


class StoryboardSpec(BaseModel):
    title: str
    style: StyleSpec
    recurring_objects: list[RecurringObject]
    scenes: list[SceneSpec]

    @model_validator(mode="after")
    def _check(self) -> "StoryboardSpec":
        n = len(self.scenes)
        if not 6 <= n <= 14:
            raise ValueError(f"storyboard must have 8-12 scenes (6-14 tolerated), got {n}")
        nums = [s.scene_number for s in self.scenes]
        if nums != list(range(1, n + 1)):
            raise ValueError(f"scene numbers must be 1..{n} in order, got {nums}")
        prev_end = 0.0
        for s in self.scenes:
            if s.end_s <= s.start_s:
                raise ValueError(f"scene {s.scene_number}: end_s must be after start_s")
            if abs(s.start_s - prev_end) > 0.6:
                raise ValueError(f"scene {s.scene_number}: gap/overlap in timeline at {s.start_s}s")
            prev_end = s.end_s
            if s.render_method == "programmatic" and not s.template:
                raise ValueError(f"scene {s.scene_number}: programmatic scenes need a template")
            if s.render_method != "programmatic" and not s.generation_prompt:
                raise ValueError(f"scene {s.scene_number}: AI scenes need a generation_prompt")
        return self


# ---------------------------------------------------------------- QC & metadata
class EditorialReview(BaseModel):
    narration_matches_visuals: bool
    unsupported_claims: list[str]
    continuity_problems: list[str]
    clarity_issues: list[str]
    brand_issues: list[str]
    viewer_experience_notes: str
    scores: dict[str, int] = {}


class Disclosure(BaseModel):
    ai_generated_visuals: bool
    realistic_synthetic_media: bool = Field(description="True only if realistic people/events/places are depicted")
    paid_promotion: bool
    notes: str = ""


class PublishMetadata(BaseModel):
    youtube_title_candidates: list[str]
    youtube_title: str
    youtube_description: str
    instagram_caption: str
    tiktok_caption: str
    facebook_caption: str
    hashtags: list[str]
    call_to_action: str
    cover_text: str
    disclosure: Disclosure

    @field_validator("hashtags")
    @classmethod
    def _few_hashtags(cls, v: list[str]) -> list[str]:
        return [h if h.startswith("#") else f"#{h}" for h in v][:6]

    @field_validator("youtube_title")
    @classmethod
    def _title_len(cls, v: str) -> str:
        if len(v) > 100:
            raise ValueError("YouTube titles are limited to 100 characters")
        return v


class ExecutiveNarrative(BaseModel):
    summary: str
    inferences: list[str]
    recommendations: list[str]
