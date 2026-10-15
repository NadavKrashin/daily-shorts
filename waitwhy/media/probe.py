"""FFmpeg/FFprobe-based technical QC of a rendered file."""
from __future__ import annotations

import json
import re
import subprocess
from fractions import Fraction
from pathlib import Path


def ffprobe(path: Path) -> dict:
    out = subprocess.run(["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)],
                         capture_output=True, text=True, timeout=120)
    if out.returncode != 0:
        return {"error": out.stderr.strip() or "ffprobe failed"}
    return json.loads(out.stdout)


def _run_filter(path: Path, args: list[str], timeout: int = 600) -> str:
    out = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), *args, "-f", "null", "-"],
                         capture_output=True, text=True, timeout=timeout)
    return out.stderr


def black_segments(path: Path, min_d: float = 0.5, pix_th: float = 0.10) -> list[tuple[float, float]]:
    err = _run_filter(path, ["-vf", f"blackdetect=d={min_d}:pix_th={pix_th}", "-an"])
    return [(float(a), float(b)) for a, b in re.findall(r"black_start:([\d.]+) black_end:([\d.]+)", err)]


def silence_segments(path: Path, noise_db: float = -45.0, min_d: float = 1.5) -> list[tuple[float, float]]:
    err = _run_filter(path, ["-af", f"silencedetect=noise={noise_db}dB:d={min_d}", "-vn"])
    starts = [float(x) for x in re.findall(r"silence_start: ([\d.]+)", err)]
    ends = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", err)]
    return list(zip(starts, ends + [None] * (len(starts) - len(ends))))


def loudness(path: Path) -> dict:
    err = _run_filter(path, ["-af", "ebur128=peak=true", "-vn"])
    i = re.findall(r"I:\s+(-?[\d.]+) LUFS", err)
    tp = re.findall(r"Peak:\s+(-?[\d.]+) dBFS", err)
    return {"integrated_lufs": float(i[-1]) if i else None, "true_peak_dbfs": float(tp[-1]) if tp else None}


def decode_errors(path: Path) -> list[str]:
    out = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-f", "null", "-"], capture_output=True, text=True,
                         timeout=600)
    return [line for line in out.stderr.splitlines() if line.strip()]


def technical_report(path: Path, cfg_video: dict) -> dict:
    """Return {checks: [...], probe: {...}} - every check is mandatory for publication."""
    checks: list[dict] = []

    def add(name, passed, detail, mandatory=True):
        checks.append({"name": name, "category": "technical", "passed": bool(passed), "mandatory": mandatory,
                       "detail": detail})

    if not Path(path).exists():
        add("file_exists", False, f"{path} missing")
        return {"checks": checks, "probe": {}}
    p = ffprobe(path)
    if "error" in p:
        add("container_integrity", False, p["error"])
        return {"checks": checks, "probe": p}
    v = next((s for s in p["streams"] if s["codec_type"] == "video"), None)
    a = next((s for s in p["streams"] if s["codec_type"] == "audio"), None)
    dur = float(p["format"].get("duration", 0))
    add("video_stream", v is not None, "present" if v else "no video stream")
    add("audio_stream", a is not None, "present" if a else "no audio stream")
    if v:
        add("resolution", (v["width"], v["height"]) == (cfg_video["width"], cfg_video["height"]),
            f"{v['width']}x{v['height']}")
        fps = float(Fraction(v.get("avg_frame_rate", "0/1"))) if v.get("avg_frame_rate", "0/0") != "0/0" else 0
        add("frame_rate", abs(fps - cfg_video["fps"]) < 0.05, f"{fps:.3f} fps")
        add("video_codec", v["codec_name"] == cfg_video.get("video_codec", "h264"), v["codec_name"])
        add("pixel_format", v.get("pix_fmt") == "yuv420p", v.get("pix_fmt"))
        nb = int(v.get("nb_frames", 0) or 0)
        expected = round(dur * cfg_video["fps"])
        add("frame_count", nb == 0 or abs(nb - expected) <= 2, f"{nb} frames vs {expected} expected")
    if a:
        add("audio_codec", a["codec_name"] == cfg_video.get("audio_codec", "aac"), a["codec_name"])
    add("duration", cfg_video["min_duration_seconds"] <= dur <= cfg_video["max_duration_seconds"], f"{dur:.2f}s")
    errs = decode_errors(path)
    add("decode_clean", not errs, f"{len(errs)} decoder errors" + (f": {errs[0]}" if errs else ""))
    blacks = black_segments(path)
    add("no_black_frames", not blacks, f"black segments: {blacks}" if blacks else "none >= 0.5s")
    sil = silence_segments(path) if a else []
    add("no_excessive_silence", not sil, f"silences >= 1.5s: {sil}" if sil else "none >= 1.5s")
    lo = loudness(path) if a else {}
    li = lo.get("integrated_lufs")
    add("loudness", li is not None and abs(li - cfg_video.get("target_loudness_lufs", -14)) <= 1.5,
        f"{li} LUFS (target {cfg_video.get('target_loudness_lufs', -14)})")
    tp = lo.get("true_peak_dbfs")
    add("true_peak", tp is not None and tp <= -0.5, f"{tp} dBFS")
    return {"checks": checks, "probe": {"duration_s": dur, "video": v, "audio": a, "format": p["format"],
                                        "loudness": lo, "black": blacks, "silence": sil}}
