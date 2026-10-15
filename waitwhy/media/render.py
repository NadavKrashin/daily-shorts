"""Scene clip rendering and final assembly (FFmpeg).

* Programmatic scenes: frames drawn by ``templates`` and piped as raw RGB into libx264.
* AI image scenes: the still is animated with the ``image_kenburns`` template.
* AI video scenes: provider clip is scaled/cropped to 9:16, looped/trimmed to length.
* Assembly: scene clips are rendered with a short "handle" so ``xfade`` transitions never shift the
  narration timeline; captions are burned in with libass; audio is muxed as AAC.
"""
from __future__ import annotations

import hashlib
import json
import multiprocessing
import subprocess
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from waitwhy.media import style as st
from waitwhy.media.templates import H, W, FrameCtx, render_frame

RENDERER_VERSION = "1.0.0"   # bump when templates change visually -> invalidates scene-clip cache
XFADE = {"crossfade": ("fade", 0.30), "slide": ("slideup", 0.35), "zoom": ("zoomin", 0.35), "cut": ("fade", 0.04)}


def scene_cache_key(scene: dict, duration: float, extras: dict, asset_hash: str | None = None) -> str:
    blob = json.dumps({"scene": scene, "dur": round(duration, 3), "extras": extras, "asset": asset_hash,
                       "v": RENDERER_VERSION}, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode()).hexdigest()


def _encode_cmd(out: Path, fps: int) -> list[str]:
    return ["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(fps),
            "-i", "-", "-c:v", "libx264", "-preset", "medium", "-crf", "16", "-pix_fmt", "yuv420p", str(out)]


def render_scene_clip(job: dict) -> str:
    """Render one scene to an mp4 (no audio). ``job`` is plain data so it can run in a worker process."""
    scene, dur, out = job["scene"], float(job["duration"]), Path(job["out"])
    fps = int(job.get("fps", 30))
    pal = st.Palette(job.get("palette"))
    method = scene.get("render_method", "programmatic")
    if method == "ai_video" and job.get("asset_path"):
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-stream_loop", "-1", "-i", job["asset_path"], "-t", f"{dur:.3f}",
                        "-vf", f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},fps={fps},format=yuv420p",
                        "-an", "-c:v", "libx264", "-preset", "medium", "-crf", "16", str(out)], check=True, timeout=600)
        return str(out)
    tpl = "image_kenburns" if method == "ai_image" else scene["template"]
    params = job.get("params") or {}
    n = max(1, round(dur * fps))
    proc = subprocess.Popen(_encode_cmd(out, fps), stdin=subprocess.PIPE)
    try:
        for i in range(n):
            ctx = FrameCtx(t=i / fps, dur=float(job.get("nominal", dur)), params=params, pal=pal,
                           on_screen_text=scene.get("on_screen_text", ""),
                           asset_path=Path(job["asset_path"]) if job.get("asset_path") else None,
                           extras=job.get("extras", {}))
            proc.stdin.write(render_frame(tpl, ctx).tobytes())
    finally:
        proc.stdin.close()
        code = proc.wait(timeout=600)
    if code != 0:
        raise RuntimeError(f"ffmpeg encode failed for scene {scene.get('scene_number')}")
    return str(out)


def render_scenes(jobs: list[dict], workers: int = 3) -> list[str]:
    if workers <= 1 or len(jobs) <= 1:
        return [render_scene_clip(j) for j in jobs]
    # spawn (not fork): workers run alongside heartbeat threads, and forking a threaded process is unsafe
    with ProcessPoolExecutor(max_workers=workers, mp_context=multiprocessing.get_context("spawn")) as ex:
        return list(ex.map(render_scene_clip, jobs))


def assemble(clips: list[Path], durations: list[float], transitions: list[str], audio: Path, ass: Path | None,
             out: Path, fps: int = 30, fonts_dir: str | None = None) -> Path:
    """clips[i] must be durations[i] + handle long (except the last). transitions[i] joins clip i -> i+1."""
    total = sum(durations)
    inputs: list[str] = []
    for c in clips:
        inputs += ["-i", str(c)]
    inputs += ["-i", str(audio)]
    parts, prev, offset = [], "[0:v]", 0.0
    for i in range(1, len(clips)):
        offset += durations[i - 1]
        kind, td = XFADE.get(transitions[i - 1], XFADE["crossfade"])
        label = f"[x{i}]"
        parts.append(f"{prev}[{i}:v]xfade=transition={kind}:duration={td}:offset={offset:.3f}{label}")
        prev = label
    vf = prev
    post = f"fps={fps},format=yuv420p"
    if ass:
        esc = str(ass).replace(":", r"\:").replace("'", r"\'")
        fd = f":fontsdir={fonts_dir}" if fonts_dir else ""
        post = f"subtitles='{esc}'{fd}," + post
    parts.append(f"{vf}{post}[vout]")
    cmd = ["ffmpeg", "-y", "-v", "error", *inputs, "-filter_complex", ";".join(parts), "-map", "[vout]",
           "-map", f"{len(clips)}:a", "-t", f"{total:.3f}", "-c:v", "libx264", "-preset", "medium", "-crf", "18",
           "-profile:v", "high", "-pix_fmt", "yuv420p", "-r", str(fps), "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
           "-movflags", "+faststart", str(out)]
    subprocess.run(cmd, check=True, timeout=1800)
    return out


def thumbnail(scene: dict, params: dict, cover_text: str, out: Path, palette: dict | None, extras: dict,
              t: float = 2.5) -> Path:
    pal = st.Palette(palette)
    img = render_frame(scene["template"], FrameCtx(t=t, dur=max(t + 1, 5.0), params=params, pal=pal,
                                                   on_screen_text="", extras=extras))
    from PIL import ImageDraw

    from waitwhy.media.templates import top_scrim
    top_scrim(img, 900)
    f = st.font("Inter-Black", 120)
    lines = st.wrap(cover_text.upper(), f, W - 160)
    for i, line in enumerate(lines[:3]):
        st.text_center(img, (W / 2, 420 + i * 140), line, f, pal.accent if i == len(lines[:3]) - 1 else pal.text,
                       stroke=8, stroke_fill=(10, 15, 30))
    ImageDraw.Draw(img)
    img.save(out, quality=92)
    return out
