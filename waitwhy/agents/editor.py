"""Agent H - Video editor: storyboard (source of truth) + narration + visuals -> finished deliverables."""
from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

import numpy as np
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from waitwhy.agents.production import narration_assets
from waitwhy.media import audio as au
from waitwhy.media import captions as cap
from waitwhy.media import render as rd
from waitwhy.models import GeneratedAsset, Storyboard, Video, VideoVersion
from waitwhy.providers import registry

LEAD_S, TAIL_S, HANDLE_S, MIN_SCENE_S = 0.15, 0.30, 0.40, 2.5


def _scene_params(spec: dict) -> dict:
    out = {}
    for p in spec.get("template_params", []):
        try:
            out[p["key"]] = json.loads(p["value"])
        except (json.JSONDecodeError, TypeError):
            out[p["key"]] = p["value"]
    return out


def render(session: Session, cfg: dict, video: Video, job_id=None, workers: int = 3) -> VideoVersion:
    board = session.get(Storyboard, video.current_storyboard_id)
    scenes = list(board.scenes)
    store = registry.storage(cfg)
    narr = narration_assets(session, board)
    work = Path(tempfile.mkdtemp(prefix="ww-edit-"))
    fps = cfg["video"]["fps"]
    palette = {**cfg["brand"]["palette"]}
    extras = {"brand_name": cfg["business_name"], "tagline": cfg["tagline"]}

    # 1) timing: each scene lasts as long as its narration (+ breathing room)
    durations, specs, params = [], [], []
    for sc, a in zip(scenes, narr):
        spec = sc.data
        p = _scene_params(spec)
        d = max(MIN_SCENE_S, LEAD_S + a.duration_s + TAIL_S) + float(p.get("end_card_s", 0) or 0)
        durations.append(round(d * fps) / fps)  # frame-aligned
        specs.append(spec)
        params.append(p)
    starts = list(np.cumsum([0.0] + durations[:-1]))

    # 2) scene clips (reuse cached renders)
    jobs, clip_paths, reused = [], [], 0
    for i, (sc, spec, p, d) in enumerate(zip(scenes, specs, params, durations)):
        asset_path, asset_hash = None, None
        if sc.render_method != "programmatic":
            a = session.execute(select(GeneratedAsset).where(
                GeneratedAsset.scene_id == sc.id, GeneratedAsset.kind.in_(["scene_image", "scene_video"]),
                GeneratedAsset.status == "succeeded").order_by(GeneratedAsset.created_at.desc())).scalars().first()
            if a is None:
                raise RuntimeError(f"scene {sc.scene_number} has no generated visual")
            asset_path, asset_hash = str(store.local_path(a.storage_key)), a.cache_key
        if spec.get("template") == "highway_flyover" and i > 0:
            p = {**p, "prev_dur": durations[i - 1]}
        length = d + (HANDLE_S if i < len(scenes) - 1 else 0)
        key = rd.scene_cache_key(spec, length, {"palette": palette, **extras, "p": p}, asset_hash)
        cached = session.execute(select(GeneratedAsset).where(
            GeneratedAsset.scene_id == sc.id, GeneratedAsset.kind == "scene_clip", GeneratedAsset.cache_key == key,
            GeneratedAsset.status == "succeeded")).scalars().first()
        if cached and store.exists(cached.storage_key):
            clip_paths.append(store.local_path(cached.storage_key))
            reused += 1
            continue
        out = work / f"scene_{sc.scene_number:02d}.mp4"
        jobs.append({"scene": spec, "duration": length, "nominal": d, "out": str(out), "fps": fps, "palette": palette,
                     "params": p, "extras": extras, "asset_path": asset_path, "_scene_id": str(sc.id), "_key": key,
                     "_idx": i})
        clip_paths.append(out)
    rendered = rd.render_scenes([{k: v for k, v in j.items() if not k.startswith("_")} for j in jobs], workers=workers)
    for j, path in zip(jobs, rendered):
        skey = store.put_file(Path(path), f"videos/{video.slug}/clips/scene_{j['_idx'] + 1:02d}_{j['_key'][:10]}.mp4")
        session.add(GeneratedAsset(video_id=video.id, scene_id=scenes[j["_idx"]].id, kind="scene_clip",
                                   provider="programmatic", model=f"renderer-{rd.RENDERER_VERSION}", cache_key=j["_key"],
                                   storage_key=skey, duration_s=j["duration"], status="succeeded",
                                   rights={"license": "original work (in-house deterministic render)",
                                           "commercial_use": True, "source": "waitwhy-renderer"}))
        clip_paths[j["_idx"]] = store.local_path(skey)
    session.flush()

    # 3) audio: narration timeline + owned music bed + SFX, ducked and loudness-normalised
    total = float(sum(durations))
    n = int(total * au.SR) + au.SR
    narration = np.zeros(n, dtype=np.float32)
    sfx = np.zeros(n, dtype=np.float32)
    words_abs: list[dict] = []
    for i, (a, st_) in enumerate(zip(narr, starts)):
        x = au.decode_mono(store.local_path(a.storage_key))
        off = int((st_ + LEAD_S) * au.SR)
        narration[off: off + len(x)] += x[: max(0, n - off)]
        for w in (a.params or {}).get("words", []):
            words_abs.append({"w": w["w"], "s": round(st_ + LEAD_S + w["s"], 3), "e": round(st_ + LEAD_S + w["e"], 3)})
        if i > 0:
            wh = au.whoosh(seed=i)
            o = max(0, int((st_ - 0.22) * au.SR))
            sfx[o: o + len(wh)] += wh[: n - o]
        if specs[i].get("on_screen_text"):
            pp = au.pop()
            o = int((st_ + 0.2) * au.SR)
            sfx[o: o + len(pp)] += pp[: n - o]
    music = au.music_bed(total + 1.0)
    mix = au.mix_tracks(narration[: int(total * au.SR)], music[: int(total * au.SR)], sfx[: int(total * au.SR)])
    raw_wav = au.write_wav(work / "mix_raw.wav", mix)
    norm_wav = work / "mix.wav"
    meas = au.loudnorm_two_pass(raw_wav, norm_wav, cfg["video"]["target_loudness_lufs"], cfg["video"]["true_peak_db"])
    clip_ratio = au.clipping_ratio(au.decode_mono(norm_wav))

    # 4) captions (separate SRT deliverable + styled ASS burned in)
    chunks = cap.chunk_words(words_abs)
    (work / "captions.srt").write_text(cap.to_srt(chunks), encoding="utf-8")
    safe = cfg["video"]["caption_safe_zone"]
    (work / "captions.ass").write_text(cap.to_ass(chunks, y_center=1330, margin_lr=max(safe["left"], 100)),
                                       encoding="utf-8")

    # 5) assemble
    final = work / "final.mp4"
    transitions = [s.get("transition", "crossfade") for s in specs[1:]]
    from waitwhy.media.style import font_path
    fonts_dir = str(Path(font_path("Inter-Bold")).parent) if font_path("Inter-Bold") else None
    rd.assemble([Path(c) for c in clip_paths], durations, transitions, norm_wav, work / "captions.ass", final, fps=fps,
                fonts_dir=fonts_dir)

    # 6) thumbnail / cover
    meta = video.publish_metadata or {}
    thumb = rd.thumbnail(specs[0], params[0], meta.get("cover_text") or video.title, work / "thumbnail.jpg", palette,
                         extras)

    version_n = (session.execute(select(func.max(VideoVersion.version)).where(VideoVersion.video_id == video.id))
                 .scalar() or 0) + 1
    base = f"videos/{video.slug}/v{version_n}"
    keys = {name: store.put_file(work / name, f"{base}/{name}") for name in
            ("final.mp4", "captions.srt", "captions.ass", "thumbnail.jpg", "mix.wav")}
    rights = []
    for sc, a in zip(scenes, narr):
        rights.append({"asset": f"narration scene {sc.scene_number}", **(a.rights or {})})
    for sc in scenes:
        if sc.render_method != "programmatic":
            a = session.execute(select(GeneratedAsset).where(
                GeneratedAsset.scene_id == sc.id, GeneratedAsset.kind.in_(["scene_image", "scene_video"]),
                GeneratedAsset.status == "succeeded")).scalars().first()
            rights.append({"asset": f"visual scene {sc.scene_number}", **(a.rights or {})})
        else:
            rights.append({"asset": f"visual scene {sc.scene_number}", "license": "original work (in-house render)",
                           "commercial_use": True, "source": "waitwhy-renderer"})
    rights.append({"asset": "music bed + sfx", "license": "original procedural composition (in-house)",
                   "commercial_use": True, "source": "waitwhy-audio"})
    manifest = {
        "renderer_version": rd.RENDERER_VERSION, "fps": fps, "total_s": round(total, 3),
        "scenes": [{"scene_number": sc.scene_number, "start_s": round(s, 3), "end_s": round(s + d, 3),
                    "template": sc.template, "render_method": sc.render_method,
                    "narration_start_s": round(s + LEAD_S, 3), "narration_end_s": round(s + LEAD_S + a.duration_s, 3),
                    "clip": str(clip)} for sc, s, d, a, clip in zip(scenes, starts, durations, narr, clip_paths)],
        "caption_words": len(words_abs), "caption_text": " ".join(w["w"] for w in words_abs),
        "audio": {"loudnorm_input": meas, "clipping_ratio": clip_ratio}, "rights": rights,
        "scene_clips_reused": reused, "deliverables": keys,
    }
    vv = VideoVersion(video_id=video.id, version=version_n, storyboard_id=board.id, storage_key=keys["final.mp4"],
                      captions_key=keys["captions.srt"], thumbnail_key=keys["thumbnail.jpg"], manifest=manifest,
                      duration_s=total, status="rendered",
                      change_note=f"{len(jobs)} scenes rendered, {reused} reused")
    session.add(vv)
    session.flush()
    (work / "manifest.json").write_text(json.dumps(manifest, indent=1, default=str))
    store.put_file(work / "manifest.json", f"{base}/manifest.json")
    video.current_version_id = vv.id
    shutil.rmtree(work, ignore_errors=True)
    return vv
