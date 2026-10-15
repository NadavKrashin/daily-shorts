import subprocess
from pathlib import Path

import pytest

from waitwhy.media import captions, probe, render, style
from waitwhy.media.templates import TEMPLATES, FrameCtx, render_frame
from waitwhy.media.traffic import jam_drift_kmh, simulate
from waitwhy.settings import load_company_config

CFG = load_company_config()


@pytest.mark.parametrize("name", sorted(TEMPLATES))
def test_every_template_renders_a_frame(name):
    img = render_frame(name, FrameCtx(t=1.0, dur=4.0, params={"mode": "jam"} if name == "ring_road" else {},
                                      pal=style.Palette(), on_screen_text="TEST", extras={"brand_name": "W"}))
    assert img.size == (1080, 1920)


def test_simulation_produces_backward_moving_jam():
    sim = simulate("jam", 300.0)
    xs, vs, _ = sim.at(260)
    assert vs.min() * 3.6 < 2.0                   # cars come to a (near) stop: a real jam
    assert jam_drift_kmh(sim) < -1.0              # and it moves against the traffic
    smooth = simulate("jam", 300.0, smoother_on=0.0)
    assert smooth.at(260)[1].min() * 3.6 > 10.0   # one smoothing car prevents full stops


def test_captions_srt_and_ass():
    words = [{"w": w, "s": i * 0.4, "e": i * 0.4 + 0.35} for i, w in enumerate("Nobody crashed. Nobody merged.".split())]
    chunks = captions.chunk_words(words)
    assert [c["text"] for c in chunks] == ["Nobody crashed.", "Nobody merged."]
    srt = captions.to_srt(chunks)
    assert "00:00:00,000 --> " in srt and "Nobody merged." in srt
    ass = captions.to_ass(chunks)
    assert ass.count("Dialogue:") == 4 and "PlayResY: 1920" in ass


def _make(path: Path, size="1080x1920", dur=3, audio=True):
    cmd = ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"testsrc2=size={size}:rate=30:duration={dur}"]
    if audio:
        cmd += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={dur}"]
    cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p"] + (["-c:a", "aac"] if audio else []) + ["-shortest", str(path)]
    subprocess.run(cmd, check=True)
    return path


def _failed(report):
    return {c["name"] for c in report["checks"] if not c["passed"]}


def test_qc_rejects_invalid_media(tmp_path):
    bad = tmp_path / "corrupt.mp4"
    bad.write_bytes(b"\x00\x00not a video")
    assert "container_integrity" in _failed(probe.technical_report(bad, CFG["video"]))
    assert "file_exists" in _failed(probe.technical_report(tmp_path / "missing.mp4", CFG["video"]))


def test_qc_flags_wrong_resolution_duration_and_missing_audio(tmp_path):
    p = _make(tmp_path / "small.mp4", size="640x360", dur=3, audio=False)
    failed = _failed(probe.technical_report(p, CFG["video"]))
    assert {"resolution", "duration", "audio_stream"} <= failed


def test_scene_clip_render_and_assembly(tmp_path):
    pal = {}
    jobs = []
    for i, (tpl, d) in enumerate([("title_card", 1.0), ("end_card", 1.0)]):
        jobs.append({"scene": {"template": tpl, "scene_number": i + 1, "render_method": "programmatic"},
                     "duration": d + (0.4 if i == 0 else 0), "nominal": d, "out": str(tmp_path / f"s{i}.mp4"),
                     "fps": 30, "palette": pal, "params": {"headline": "Hi"}, "extras": {}})
    clips = render.render_scenes(jobs, workers=1)
    audio = tmp_path / "a.wav"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=300:duration=2", "-ar", "48000",
                    str(audio)], check=True)
    out = render.assemble([Path(c) for c in clips], [1.0, 1.0], ["crossfade"], audio, None, tmp_path / "f.mp4")
    rep = probe.technical_report(out, {**CFG["video"], "min_duration_seconds": 1})
    assert {"resolution", "frame_rate", "video_codec", "audio_codec", "decode_clean"}.isdisjoint(_failed(rep))
    assert abs(rep["probe"]["duration_s"] - 2.0) < 0.1
