"""Audio: narration timeline, procedurally-synthesised (owned) music bed + SFX, ducking, two-pass EBU R128
loudness normalisation. Everything here is generated in-house => no third-party licensing exposure."""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import numpy as np

SR = 48000


def decode_mono(path: Path, sr: int = SR) -> np.ndarray:
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-ac", "1", "-ar", str(sr), "-f", "s16le", "-"],
                         capture_output=True, check=True, timeout=120).stdout
    return np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0


def write_wav(path: Path, stereo: np.ndarray, sr: int = SR) -> Path:
    import wave

    data = np.clip(stereo, -1, 1)
    pcm = (data * 32767).astype("<i2")
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(2 if pcm.ndim == 2 else 1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(pcm.tobytes())
    return path


def trim_silence(x: np.ndarray, thresh: float = 0.01, pad_s: float = 0.04) -> np.ndarray:
    idx = np.where(np.abs(x) > thresh)[0]
    if len(idx) == 0:
        return x
    pad = int(pad_s * SR)
    return x[max(0, idx[0] - pad): min(len(x), idx[-1] + pad)]


def music_bed(duration: float, seed: int = 1, bpm: float = 96.0) -> np.ndarray:
    """Soft, curious synth pad + plucks (original composition generated from code)."""
    n = int(duration * SR)
    t = np.arange(n) / SR
    rng = np.random.default_rng(seed)
    # I - vi - IV - V in C major, voiced as pads
    chords = [[60, 64, 67, 71], [57, 60, 64, 67], [53, 57, 60, 64], [55, 59, 62, 65]]
    bar = 4 * 60.0 / bpm
    out = np.zeros(n, dtype=np.float32)

    def hz(m):
        return 440.0 * 2 ** ((m - 69) / 12)

    for k in range(int(duration / bar) + 1):
        ch = chords[k % 4]
        s0, s1 = int(k * bar * SR), min(n, int((k + 1) * bar * SR) + int(0.5 * SR))
        if s0 >= n:
            break
        tt = t[s0:s1] - k * bar
        env = np.minimum(1.0, tt / 0.6) * np.exp(-np.maximum(0, tt - bar) * 3)
        for m in ch:
            f = hz(m - 12)
            out[s0:s1] += 0.05 * env * (np.sin(2 * np.pi * f * tt) + 0.3 * np.sin(2 * np.pi * 2 * f * tt + 0.3))
        # plucked arpeggio (eighth notes)
        for j in range(8):
            ps = s0 + int(j * bar / 8 * SR)
            pe = min(n, ps + int(0.5 * SR))
            if ps >= n:
                break
            pt = t[ps:pe] - t[ps]
            f = hz(ch[(j * 3 + k) % 4] + 12)
            out[ps:pe] += 0.035 * np.exp(-pt * 9) * np.sin(2 * np.pi * f * pt) * (0.7 + 0.3 * rng.random())
    # gentle low-pass via moving average to keep it warm
    out = np.convolve(out, np.ones(6) / 6, mode="same")
    fade = int(1.0 * SR)
    out[:fade] *= np.linspace(0, 1, fade)
    out[-fade:] *= np.linspace(1, 0, fade)
    return out


def whoosh(dur: float = 0.45, seed: int = 0) -> np.ndarray:
    n = int(dur * SR)
    rng = np.random.default_rng(seed)
    noise = rng.normal(0, 1, n).astype(np.float32)
    # sweep a resonant band-pass-ish filter by mixing smoothed noise of decreasing width
    out = np.zeros(n, dtype=np.float32)
    for w, g in ((40, 0.6), (12, 0.4)):
        out += g * np.convolve(noise, np.ones(w) / w, mode="same")
    env = np.sin(np.linspace(0, np.pi, n)) ** 2
    return 0.25 * out * env


def pop(dur: float = 0.12, freq: float = 880.0) -> np.ndarray:
    t = np.arange(int(dur * SR)) / SR
    return (0.22 * np.exp(-t * 35) * np.sin(2 * np.pi * freq * t * (1 + 0.5 * np.exp(-t * 40)))).astype(np.float32)


def envelope(x: np.ndarray, win_s: float = 0.08) -> np.ndarray:
    w = max(1, int(win_s * SR))
    return np.sqrt(np.convolve(x ** 2, np.ones(w) / w, mode="same"))


def mix_tracks(narration: np.ndarray, music: np.ndarray, sfx: np.ndarray, music_gain_db: float = -16.0,
               duck_db: float = -10.0) -> np.ndarray:
    n = max(len(narration), len(music), len(sfx))
    pad = lambda a: np.pad(a, (0, n - len(a)))  # noqa: E731
    narr, mus, fx = pad(narration), pad(music), pad(sfx)
    env = envelope(narr)
    voice_on = np.clip(env / 0.02, 0, 1)
    smooth = np.convolve(voice_on, np.ones(int(0.25 * SR)) / int(0.25 * SR), mode="same")
    gain = 10 ** ((music_gain_db + duck_db * smooth) / 20)
    mono = narr + mus * gain + fx
    stereo = np.stack([mono, mono], axis=1)
    return stereo


def loudnorm_two_pass(src: Path, dst: Path, target_i: float = -14.0, tp: float = -1.5, lra: float = 11.0) -> dict:
    first = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(src), "-af",
                            f"loudnorm=I={target_i}:TP={tp}:LRA={lra}:print_format=json", "-f", "null", "-"],
                           capture_output=True, text=True, timeout=300)
    m = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", first.stderr, re.S)
    if not m:
        raise RuntimeError("loudnorm measurement failed")
    meas = json.loads(m.group(0))
    af = (f"loudnorm=I={target_i}:TP={tp}:LRA={lra}:measured_I={meas['input_i']}:measured_TP={meas['input_tp']}:"
          f"measured_LRA={meas['input_lra']}:measured_thresh={meas['input_thresh']}:offset={meas['target_offset']}:"
          f"linear=true:print_format=summary")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(src), "-af", af, "-ar", str(SR), str(dst)], check=True,
                   timeout=300)
    return meas


def clipping_ratio(x: np.ndarray, thresh: float = 0.999) -> float:
    return float(np.mean(np.abs(x) >= thresh)) if len(x) else 0.0
