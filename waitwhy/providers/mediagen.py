"""Image / video generation providers.

Higgsfield API (verified 2026-10-15 at docs.higgsfield.ai):
  base https://api.higgsfield.ai, header ``Authorization: Key <id>:<secret>``; the MODEL is selected by
  the URL path (e.g. ``/higgsfield-ai/soul/v2/standard``); submit returns ``request_id`` +
  ``status_url``; statuses queued|in_progress|completed|failed|nsfw|canceled; completed payloads carry
  ``images[].url`` or ``video.url``. Outputs are kept >= 7 days, so we download immediately.
  Per-model body fields differ: configure them in company.yaml -> higgsfield.*_body_defaults after
  checking https://docs.higgsfield.ai/docs/models.md. Content is licensed for commercial use per
  Higgsfield's API terms (re-confirm before launch).

Note: the Higgsfield *MCP connector* used interactively in Claude sessions is a different surface;
the backend needs an API key from https://open.higgsfield.ai (separate pay-as-you-go wallet).
"""
from __future__ import annotations

import hashlib
import subprocess
import time
from pathlib import Path

import httpx
from PIL import Image, ImageDraw, ImageFilter

from waitwhy.errors import AuthError, PermanentError, PolicyError, TransientError
from waitwhy.providers.base import GenerationRequest, GenerationResult
from waitwhy.providers.pricing import HIGGSFIELD_IMAGE_USD_DEFAULT, HIGGSFIELD_VIDEO_USD_PER_SECOND_DEFAULT


class HiggsfieldAPI:
    name = "higgsfield"

    def __init__(self, key_id: str, key_secret: str, cfg: dict, base_url: str = "https://api.higgsfield.ai"):
        if not key_id or not key_secret:
            raise AuthError("HIGGSFIELD_API_KEY and HIGGSFIELD_API_SECRET must be set")
        self.auth = f"Key {key_id}:{key_secret}"
        self.cfg = cfg
        self.base = base_url.rstrip("/")

    def estimate_cost(self, req: GenerationRequest) -> float:
        if req.kind == "video":
            return round(req.duration_s * float(self.cfg.get("video_usd_per_second", HIGGSFIELD_VIDEO_USD_PER_SECOND_DEFAULT)), 4)
        return float(self.cfg.get("image_usd", HIGGSFIELD_IMAGE_USD_DEFAULT))

    def _request(self, method: str, url: str, **kw) -> dict:
        try:
            r = httpx.request(method, url, headers={"Authorization": self.auth, "Content-Type": "application/json"},
                              timeout=60, **kw)
        except httpx.HTTPError as e:
            raise TransientError(f"higgsfield network error: {e}") from e
        if r.status_code in (401, 403):
            raise AuthError(f"higgsfield auth failed ({r.status_code})")
        if r.status_code == 402:
            raise PermanentError("higgsfield wallet balance exhausted - top up required")
        if r.status_code == 429 or r.status_code >= 500:
            raise TransientError(f"higgsfield {r.status_code}: {r.text[:200]}")
        if r.status_code >= 400:
            raise PermanentError(f"higgsfield {r.status_code}: {r.text[:300]}")
        return r.json()

    def generate(self, req: GenerationRequest, out_path: Path) -> GenerationResult:
        started = time.monotonic()
        if req.kind == "video":
            path = req.model or self.cfg["video_model_path"]
            body = dict(self.cfg.get("video_body_defaults", {}))
            body.update({"prompt": req.prompt})
            if req.reference_image_paths:
                raise PermanentError("image-to-video needs public image URLs; upload references to storage first")
        else:
            path = req.model or self.cfg["image_model_path"]
            body = dict(self.cfg.get("image_body_defaults", {}))
            body.update({"prompt": req.prompt})
        if req.seed is not None and self.cfg.get("supports_seed"):
            body["seed"] = req.seed
        sub = self._request("POST", f"{self.base}/{path.lstrip('/')}", json=body)
        status_url = sub.get("status_url") or f"{self.base}/requests/{sub['request_id']}/status"
        deadline = time.monotonic() + float(self.cfg.get("max_wait_s", 900))
        delay = 3.0
        while True:
            st = self._request("GET", status_url)
            status = st.get("status")
            if status == "completed":
                break
            if status == "nsfw":
                raise PolicyError("higgsfield flagged the output as NSFW; prompt must be revised")
            if status in ("failed", "canceled"):
                raise TransientError(f"higgsfield generation {status}: {st.get('error')}")
            if time.monotonic() > deadline:
                raise TransientError("higgsfield generation timed out")
            time.sleep(delay)
            delay = min(delay * 1.5, 20.0)
        url = (st.get("video") or {}).get("url") if req.kind == "video" else (st.get("images") or [{}])[0].get("url")
        if not url:
            raise PermanentError(f"higgsfield completed without an output url: {list(st)}")
        suffix = ".mp4" if req.kind == "video" else ".png"
        out_path = Path(out_path).with_suffix(suffix)
        with httpx.stream("GET", url, timeout=120) as r:
            r.raise_for_status()
            with open(out_path, "wb") as fh:
                for chunk in r.iter_bytes():
                    fh.write(chunk)
        return GenerationResult(path=out_path, provider=self.name, model=path, external_id=sub.get("request_id"),
                                cost_usd=self.estimate_cost(req), seconds=time.monotonic() - started,
                                rights={"license": "Higgsfield API output - commercial use per API terms",
                                        "commercial_use": True, "source": "higgsfield", "model": path,
                                        "ai_generated": True})


class MockMediaGen:
    """Deterministic placeholder visuals (clearly watermarked MOCK; never publishable)."""

    name = "mock"

    def __init__(self, width: int = 1080, height: int = 1920):
        self.w, self.h = width, height

    def estimate_cost(self, req: GenerationRequest) -> float:
        return round(req.duration_s * 0.10, 4) if req.kind == "video" else 0.04  # pretend prices -> budget tests

    def _image(self, prompt: str, path: Path) -> Path:
        seed = int(hashlib.sha256(prompt.encode()).hexdigest()[:8], 16)
        hue = seed % 360
        img = Image.new("RGB", (self.w, self.h))
        d = ImageDraw.Draw(img)
        for y in range(self.h):
            k = y / self.h
            d.line([(0, y), (self.w, y)], fill=(int(20 + 40 * k), int(30 + (hue % 80) * k), int(70 + 90 * k)))
        for i in range(6):
            r = 120 + (seed >> i) % 160
            cx, cy = (seed * (i + 3)) % self.w, (seed * (i + 7)) % self.h
            d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(56, 189, 248) if i % 2 else (250, 204, 21))
        img = img.filter(ImageFilter.GaussianBlur(18))
        d = ImageDraw.Draw(img)
        d.rectangle([0, self.h // 2 - 60, self.w, self.h // 2 + 60], fill=(0, 0, 0))
        d.text((40, self.h // 2 - 20), "MOCK AI VISUAL - NOT FOR PUBLICATION", fill=(255, 80, 80))
        img.save(path)
        return path

    def generate(self, req: GenerationRequest, out_path: Path) -> GenerationResult:
        started = time.monotonic()
        img_path = self._image(req.prompt, Path(out_path).with_suffix(".png"))
        path = img_path
        if req.kind == "video":
            path = Path(out_path).with_suffix(".mp4")
            subprocess.run(["ffmpeg", "-y", "-v", "error", "-loop", "1", "-i", str(img_path), "-t", f"{req.duration_s:.2f}",
                            "-vf", f"scale={self.w}:{self.h},format=yuv420p", "-r", "30", "-c:v", "libx264",
                            "-preset", "veryfast", str(path)], check=True, timeout=300)
        return GenerationResult(path=path, provider=self.name, model="mock", external_id=None,
                                cost_usd=self.estimate_cost(req), seconds=time.monotonic() - started,
                                rights={"license": "mock placeholder", "commercial_use": False, "source": "mock"},
                                is_mock=True)
