"""Agent F (visual generation) + Agent G (voiceover & audio assets).

Idempotent and resumable: every generated asset is keyed by a hash of its inputs, so a retry or a
resumed job (e.g. after a budget block) only generates what is missing - successful scenes are never
regenerated. Each paid call is budget-checked first and committed immediately after it succeeds.
"""
from __future__ import annotations

import hashlib
import json
import tempfile
import time
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from waitwhy import prompts
from waitwhy.business import budget
from waitwhy.errors import PermanentError, TransientError
from waitwhy.models import GeneratedAsset, Storyboard, StoryboardScene, Video, Voiceover
from waitwhy.providers import registry
from waitwhy.providers.base import GenerationRequest


def _key(*parts) -> str:
    return hashlib.sha256(json.dumps(parts, sort_keys=True, default=str).encode()).hexdigest()


def _existing(session: Session, scene_id, kind: str, key: str) -> GeneratedAsset | None:
    return session.execute(select(GeneratedAsset).where(
        GeneratedAsset.scene_id == scene_id, GeneratedAsset.kind == kind, GeneratedAsset.cache_key == key,
        GeneratedAsset.status == "succeeded")).scalars().first()


def narration_assets(session: Session, board: Storyboard) -> list[GeneratedAsset | None]:
    out = []
    for sc in board.scenes:
        a = session.execute(select(GeneratedAsset).where(
            GeneratedAsset.scene_id == sc.id, GeneratedAsset.kind == "narration", GeneratedAsset.status == "succeeded")
            .order_by(GeneratedAsset.created_at.desc())).scalars().first()
        out.append(a)
    return out


def generate_assets(session: Session, cfg: dict, video: Video, job_id=None) -> dict:
    board = session.get(Storyboard, video.current_storyboard_id)
    scenes: list[StoryboardScene] = list(board.scenes)
    store = registry.storage(cfg)
    work = Path(tempfile.mkdtemp(prefix="ww-gen-"))
    stats = {"narration_generated": 0, "narration_reused": 0, "visuals_generated": 0, "visuals_reused": 0}

    # ---------------- Agent G: narration, scene by scene (prosody context from neighbours)
    tts = registry.tts(cfg)
    voice = getattr(tts, "voice_id", None) or getattr(tts, "voice_name", None) or tts.name
    for i, sc in enumerate(scenes):
        prev_t = scenes[i - 1].narration if i else ""
        next_t = scenes[i + 1].narration if i + 1 < len(scenes) else ""
        key = _key("tts", tts.name, voice, sc.narration, prev_t, next_t, cfg.get("elevenlabs", {}))
        if _existing(session, sc.id, "narration", key):
            stats["narration_reused"] += 1
            continue
        budget.check(session, cfg, tts.estimate_cost(sc.narration), f"narration scene {sc.scene_number}", video)
        started = time.monotonic()
        res = tts.synthesize(sc.narration, work / f"narr_{sc.scene_number:02d}", previous_text=prev_t, next_text=next_t)
        skey = store.put_file(res.path, f"videos/{video.slug}/assets/narration_{sc.scene_number:02d}_{key[:10]}{res.path.suffix}")
        asset = GeneratedAsset(video_id=video.id, scene_id=sc.id, kind="narration", provider=tts.name, model=voice,
                               prompt=sc.narration, cache_key=key, storage_key=skey, duration_s=res.duration_s,
                               status="succeeded", generation_seconds=time.monotonic() - started,
                               cost_usd=res.cost_usd, estimated_cost_usd=res.cost_usd, rights=res.rights,
                               params={"words": res.words, "characters": res.characters})
        session.add(asset)
        session.flush()
        budget.record_usage(session, cfg, provider=tts.name, model=voice, kind="tts", cost_usd=res.cost_usd,
                            video_id=video.id, units={"characters": res.characters}, is_mock=res.is_mock,
                            asset_id=asset.id)
        session.commit()  # persist progress immediately
        stats["narration_generated"] += 1

    # ---------------- Agent F: AI visuals only where the storyboard asks for them
    sb = board.data
    objects = sb.get("recurring_objects", [])
    pal = ", ".join(c["hex"] for c in sb.get("style", {}).get("palette", []))
    gen = None
    for sc in scenes:
        if sc.render_method == "programmatic":
            continue
        gen = gen or registry.mediagen(cfg)
        spec = sc.data
        kind = "video" if sc.render_method == "ai_video" else "image"
        tpl = "video_generation" if kind == "video" else "image_generation"
        prompt = prompts.render(tpl, scene_prompt=spec["generation_prompt"], palette=pal, objects=objects,
                                negative=spec.get("negative_prompt") or "clutter", camera=spec["camera_movement"],
                                motion=spec["animation_motion"], seconds=cfg["higgsfield"]["video_seconds_per_scene"],
                                continuity="; ".join(spec.get("continuity", []))).user
        req = GenerationRequest(kind=kind, prompt=prompt, negative_prompt=spec.get("negative_prompt", ""),
                                duration_s=float(cfg["higgsfield"]["video_seconds_per_scene"]), seed=1000 + sc.scene_number)
        key = _key("gen", gen.name, kind, prompt, req.duration_s, req.seed, cfg.get("higgsfield", {}))
        if _existing(session, sc.id, "scene_" + kind, key):
            stats["visuals_reused"] += 1
            continue
        failures = session.execute(select(GeneratedAsset).where(
            GeneratedAsset.scene_id == sc.id, GeneratedAsset.kind == "scene_" + kind,
            GeneratedAsset.status == "failed")).scalars().all()
        if len(failures) >= cfg["max_generation_retries_per_scene"] + 1:
            sc.status = "failed"
            raise PermanentError(f"scene {sc.scene_number}: generation failed {len(failures)} times - needs a cheaper "
                                 f"programmatic fallback or a revised prompt")
        est = gen.estimate_cost(req)
        budget.check(session, cfg, est, f"AI {kind} for scene {sc.scene_number}", video)
        asset = GeneratedAsset(video_id=video.id, scene_id=sc.id, kind="scene_" + kind, provider=gen.name,
                               prompt=prompt, negative_prompt=req.negative_prompt, seed=req.seed, cache_key=key,
                               status="running", estimated_cost_usd=est, params={"duration_s": req.duration_s},
                               retry_count=len(failures))
        session.add(asset)
        session.commit()
        try:
            res = gen.generate(req, work / f"scene_{sc.scene_number:02d}")
        except TransientError as e:
            asset.status, asset.error = "failed", str(e)
            session.commit()
            raise
        skey = store.put_file(res.path, f"videos/{video.slug}/assets/scene_{sc.scene_number:02d}_{key[:10]}{res.path.suffix}")
        asset.status, asset.storage_key, asset.cost_usd = "succeeded", skey, res.cost_usd
        asset.model, asset.external_job_id, asset.rights = res.model, res.external_id, res.rights
        asset.generation_seconds = res.seconds
        budget.record_usage(session, cfg, provider=gen.name, model=res.model, kind=kind, cost_usd=res.cost_usd,
                            video_id=video.id, units={"seconds": req.duration_s} if kind == "video" else {"images": 1},
                            is_mock=res.is_mock, asset_id=asset.id)
        sc.status = "generated"
        session.commit()
        stats["visuals_generated"] += 1

    # ---------------- Voiceover record (aggregates the per-scene clips)
    narr = narration_assets(session, board)
    if any(a is None for a in narr):
        raise PermanentError("narration missing for some scenes")
    total = sum(a.duration_s for a in narr)
    words = sum(len(a.prompt.split()) for a in narr)
    vo = Voiceover(video_id=video.id, script_id=board.script_id, provider=narr[0].provider, voice_name=narr[0].model,
                   storage_key=narr[0].storage_key, duration_s=total, words_per_minute=round(words / total * 60, 1),
                   segments=[{"scene_number": sc.scene_number, "asset_id": str(a.id), "duration_s": a.duration_s}
                             for sc, a in zip(scenes, narr)],
                   rights=narr[0].rights, cost_usd=sum(float(a.cost_usd or 0) for a in narr))
    session.add(vo)
    session.flush()
    stats["narration_seconds"] = round(total, 1)
    stats["words_per_minute"] = vo.words_per_minute
    return stats
