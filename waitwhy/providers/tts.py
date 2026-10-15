"""Text-to-speech providers.

* ElevenLabs - production brand voice (commercial use requires a PAID plan; use a stock/designed voice
  you are licensed to use, never a clone of a real person without written authorization).
  Uses ``/with-timestamps`` for exact word timings and ``previous_text``/``next_text`` so per-scene
  clips keep natural prosody across scene boundaries.
* Piper - free local TTS for development only. The bundled voice suggestion (en_US-ryan-high) is
  trained on CC BY-NC-SA data => NOT licensed for commercial use. QC blocks publication of any video
  whose narration has ``rights.commercial_use == False``.
* Mock - generates a placeholder tone with realistic duration; never publishable.
"""
from __future__ import annotations

import base64
import math
import re
import struct
import subprocess
import wave
from pathlib import Path

import httpx

from waitwhy.errors import AuthError, PermanentError, TransientError
from waitwhy.providers.base import SpeechResult
from waitwhy.providers.pricing import ELEVENLABS_USD_PER_1K_CHARS

WORD_RE = re.compile(r"\S+")


def probe_duration(path: Path) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                         capture_output=True, text=True, check=True, timeout=60)
    return float(out.stdout.strip())


def even_word_timings(text: str, duration: float, lead: float = 0.05) -> list[dict]:
    """Approximate word timings proportional to word length (used when a provider gives none)."""
    words = WORD_RE.findall(text)
    if not words:
        return []
    weights = [len(re.sub(r"\W", "", w)) + 2 for w in words]
    total = sum(weights)
    usable = max(0.1, duration - 2 * lead)
    t, out = lead, []
    for w, wt in zip(words, weights):
        d = usable * wt / total
        out.append({"w": w, "s": round(t, 3), "e": round(t + d, 3)})
        t += d
    return out


class ElevenLabsTTS:
    name = "elevenlabs"
    BASE = "https://api.elevenlabs.io/v1"

    def __init__(self, api_key: str, voice_id: str, cfg: dict):
        if not api_key or not voice_id:
            raise AuthError("ELEVENLABS_API_KEY and ELEVENLABS_VOICE_ID must be set")
        self.api_key, self.voice_id, self.cfg = api_key, voice_id, cfg

    def estimate_cost(self, text: str) -> float:
        return round(len(text) / 1000 * ELEVENLABS_USD_PER_1K_CHARS, 4)

    def synthesize(self, text, out_path, *, previous_text="", next_text=""):
        body = {
            "text": text,
            "model_id": self.cfg.get("model_id", "eleven_multilingual_v2"),
            "voice_settings": {k: self.cfg[k] for k in ("stability", "similarity_boost", "style") if k in self.cfg},
        }
        if previous_text:
            body["previous_text"] = previous_text
        if next_text:
            body["next_text"] = next_text
        try:
            r = httpx.post(f"{self.BASE}/text-to-speech/{self.voice_id}/with-timestamps",
                           params={"output_format": "mp3_44100_128"}, json=body,
                           headers={"xi-api-key": self.api_key}, timeout=120)
        except httpx.HTTPError as e:
            raise TransientError(f"elevenlabs network error: {e}") from e
        if r.status_code in (401, 403):
            raise AuthError(f"elevenlabs auth failed: {r.text[:200]}")
        if r.status_code == 429 or r.status_code >= 500:
            raise TransientError(f"elevenlabs {r.status_code}: {r.text[:200]}")
        if r.status_code >= 400:
            raise PermanentError(f"elevenlabs {r.status_code}: {r.text[:300]}")
        data = r.json()
        out_path = Path(out_path).with_suffix(".mp3")
        out_path.write_bytes(base64.b64decode(data["audio_base64"]))
        words = self._words_from_alignment(data.get("alignment") or {})
        dur = probe_duration(out_path)
        return SpeechResult(path=out_path, duration_s=dur, words=words or even_word_timings(text, dur),
                            characters=len(text), cost_usd=self.estimate_cost(text), voice_id=self.voice_id,
                            rights={"license": "ElevenLabs paid-plan commercial license", "commercial_use": True,
                                    "source": "elevenlabs", "voice_id": self.voice_id})

    @staticmethod
    def _words_from_alignment(al: dict) -> list[dict]:
        chars = al.get("characters") or []
        starts = al.get("character_start_times_seconds") or []
        ends = al.get("character_end_times_seconds") or []
        words, cur, s0, e0 = [], "", None, None
        for ch, s, e in zip(chars, starts, ends):
            if ch.isspace():
                if cur:
                    words.append({"w": cur, "s": s0, "e": e0})
                cur, s0 = "", None
                continue
            if s0 is None:
                s0 = s
            cur += ch
            e0 = e
        if cur:
            words.append({"w": cur, "s": s0, "e": e0})
        return words


class PiperTTS:
    name = "piper"

    def __init__(self, voice_path: str, length_scale: float = 1.22):
        if not voice_path or not Path(voice_path).exists():
            raise PermanentError(f"Piper voice model not found at {voice_path!r} (set PIPER_VOICE_PATH)")
        from piper import PiperVoice  # optional dependency
        from piper.config import SynthesisConfig

        self.voice = PiperVoice.load(voice_path)
        self.syn = SynthesisConfig(length_scale=length_scale)
        self.voice_name = Path(voice_path).stem

    def estimate_cost(self, text: str) -> float:
        return 0.0

    def synthesize(self, text, out_path, *, previous_text="", next_text=""):
        out_path = Path(out_path).with_suffix(".wav")
        with wave.open(str(out_path), "wb") as wf:
            self.voice.synthesize_wav(text, wf, syn_config=self.syn)
        dur = probe_duration(out_path)
        return SpeechResult(path=out_path, duration_s=dur, words=even_word_timings(text, dur), characters=len(text),
                            voice_name=self.voice_name,
                            rights={"license": "Piper voice model (dataset CC BY-NC-SA 4.0) - NON-COMMERCIAL",
                                    "commercial_use": False, "source": "piper-local",
                                    "note": "development placeholder; replace with licensed brand voice"})


class MockTTS:
    name = "mock"

    def __init__(self, wpm: float = 155.0):
        self.wpm = wpm

    def estimate_cost(self, text: str) -> float:
        return 0.0

    def synthesize(self, text, out_path, *, previous_text="", next_text=""):
        out_path = Path(out_path).with_suffix(".wav")
        n_words = max(1, len(WORD_RE.findall(text)))
        dur = max(1.0, n_words / self.wpm * 60.0 + 0.3)
        sr = 22050
        frames = bytearray()
        for i in range(int(dur * sr)):
            t = i / sr
            env = 0.5 + 0.5 * math.sin(2 * math.pi * 3.0 * t)  # syllable-like amplitude envelope
            v = 0.25 * env * math.sin(2 * math.pi * 180 * t)
            frames += struct.pack("<h", int(v * 32767))
        with wave.open(str(out_path), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sr)
            wf.writeframes(bytes(frames))
        return SpeechResult(path=out_path, duration_s=dur, words=even_word_timings(text, dur), characters=len(text),
                            voice_name="mock-tone", is_mock=True,
                            rights={"license": "mock placeholder", "commercial_use": False, "source": "mock"})
