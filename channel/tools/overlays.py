"""Explanatory text and diagram overlays for a Why in Clay episode.

Usage (inside the Higgsfield sandbox, after captions are burned):
    python3 overlays.py script_manifest.json CAPTIONS_WORDS_JSON IN.mp4 OUT.mp4 [--assembly SIDECAR.json]

The clay scenes stay text-free: video models garble letters. Every word on screen is drawn here
instead, so it is spelled exactly as written. Each block in the manifest may carry an `overlays`
list; each overlay starts when the narration reaches the phrase in `at` (looked up in the caption
timing file written by audio_to_captions.py), so the text lands on the spoken word.

Overlay types (all drawn in the upper part of the frame, clear of the bottom captions):
  card   {"text": "NO CRASH.\\nNO *CAUSE*?"}                  paper card; *word* = signal red
  stat   {"text": "22", "label": "CARS ON A RING"}             big number that counts up, label below
  chain  {"steps": ["A", "B", "*C*"], "gap": 1.5}             cause-and-effect boxes joined by arrows
  ring   {"mode": "even" | "jam", "title": "..."}             cars on a ring road (optimal-velocity
                                                               traffic model); slow cars show red
                                                               brake lights, so a jam visibly forms
  wave   {"title": "..."}                                      the same model unrolled into a lane:
                                                               cars drive right, the jam drifts left
  field  {"mode": "test" | "moons" | "fill", "title": "..."}  one eye's visual field drawn to scale
                                                               from measured blind-spot numbers: a red
                                                               dot that vanishes, full moons inside
                                                               the gap, or stripes filling it in
Common keys: "at" (phrase, required), "dur" (seconds, default 3; "rest" = until the scene ends),
"until" (phrase that ends it), "y" (centre, fraction of height).
The ring and wave diagrams come from a real car-following model, not hand-drawn motion: they
illustrate the mechanism, never data from the cited study.
"""
from __future__ import annotations

import argparse
import functools
import json
import math
import re
import subprocess
import sys
import zlib

import numpy as np
from PIL import Image, ImageDraw, ImageFont

FONT_PATHS = ["/usr/share/fonts/truetype/higgsfield/Montserrat-ExtraBold.ttf",
              "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"]
CREAM, INK, RED = (255, 246, 227), (43, 33, 24), (214, 58, 43)
EDGE, SHADOW, SAND = (214, 190, 150), (60, 40, 25, 90), (226, 200, 152)
SS = 2  # supersampling factor for smooth edges
BAND = (0.05, 0.47)  # vertical band the overlays live in (captions sit near 0.80)


@functools.lru_cache(maxsize=None)
def font(px: int) -> ImageFont.FreeTypeFont:
    for p in FONT_PATHS:
        try:
            return ImageFont.truetype(p, px)
        except OSError:
            continue
    raise SystemExit("no usable font found")


# ------------------------------------------------------------------ timing
def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", re.sub(r"[-\s]+", " ", s.lower())).strip()


class Clock:
    """Phrase -> seconds, from the caption cues (each cue: text, start, end)."""

    def __init__(self, cues: list[dict]):
        self.chars: list[tuple[str, float]] = []
        for c in cues:
            words = norm(c["text"])
            span = max(c["end"] - c["start"], 0.01)
            for i, ch in enumerate(words + " "):
                self.chars.append((ch, c["start"] + span * i / max(len(words), 1)))
        self.text = "".join(ch for ch, _ in self.chars)

    def at(self, phrase: str, after: float = 0.0) -> float:
        p = norm(phrase)
        start = 0
        while True:
            i = self.text.find(p, start)
            if i < 0:
                raise SystemExit(f"overlay phrase not found in captions after {after:.1f}s: {phrase!r}")
            if self.chars[i][1] >= after - 0.5:
                return self.chars[i][1]
            start = i + 1


# ------------------------------------------------------------------ easing
def ease_out_back(x: float) -> float:
    c = 1.70158
    x = min(max(x, 0.0), 1.0) - 1
    return 1 + (c + 1) * x ** 3 + c * x ** 2


def envelope(t: float, dur: float) -> tuple[float, float]:
    """(scale, alpha) for a pop-in / shrink-out element, t seconds after it starts."""
    if t < 0 or t > dur:
        return 0.0, 0.0
    scale = 0.55 + 0.45 * ease_out_back(t / 0.35)
    alpha = min(1.0, t / 0.15)
    out = dur - t
    if out < 0.25:
        scale *= 0.85 + 0.15 * out / 0.25
        alpha *= out / 0.25
    return scale, alpha


# ------------------------------------------------------------------ sprites
def rich_lines(text: str) -> list[list[tuple[str, bool]]]:
    """'NO *CAUSE*?' -> [[('NO ', False), ('CAUSE', True), ('?', False)]] per line."""
    return [[(seg, i % 2 == 1) for i, seg in enumerate(line.split("*")) if seg] for line in text.split("\n")]


def draw_rich(d: ImageDraw.ImageDraw, lines, f, cx: float, top: float, colour=INK, accent=RED, lh=1.12):
    for li, line in enumerate(lines):
        w = sum(f.getlength(s) for s, _ in line)
        x = cx - w / 2
        for seg, hot in line:
            d.text((x, top + li * f.size * lh), seg, font=f, fill=accent if hot else colour)
            x += f.getlength(seg)


def fit_font(lines, px: int, max_w: float) -> ImageFont.FreeTypeFont:
    while px > 20:
        f = font(px)
        if max(sum(f.getlength(s) for s, _ in ln) for ln in lines) <= max_w:
            return f
        px -= 4
    return font(px)


def paper(d: ImageDraw.ImageDraw, box, seed: int, fill=CREAM, outline=EDGE, r: float = 30 * SS) -> None:
    """A torn-paper scrap instead of a vector box: a rounded rectangle whose edge wobbles a little
    (seeded, so every frame of a card is identical), with a soft shadow and a slightly darker rim."""
    x0, y0, x1, y1 = box
    rng = np.random.default_rng(seed)
    pts = []
    for (ax, ay, bx, by) in ((x0 + r, y0, x1 - r, y0), (x1, y0 + r, x1, y1 - r),
                             (x1 - r, y1, x0 + r, y1), (x0, y1 - r, x0, y0 + r)):
        n = max(4, int(math.hypot(bx - ax, by - ay) / (26 * SS)))
        nx, ny = (by - ay), -(bx - ax)
        ln = math.hypot(nx, ny) or 1
        for i in range(n):
            t = i / n
            j = rng.uniform(-1, 1) * 5 * SS
            pts.append((ax + (bx - ax) * t + nx / ln * j, ay + (by - ay) * t + ny / ln * j))
    sh = [(x + 6 * SS, y + 12 * SS) for x, y in pts]
    d.polygon(sh, fill=SHADOW)
    d.polygon(pts, fill=fill, outline=outline, width=5 * SS)


def tilt(img: Image.Image, seed: int, max_deg: float = 1.8) -> Image.Image:
    deg = (seed % 1000) / 1000 * 2 * max_deg - max_deg
    return img.rotate(deg, resample=Image.BICUBIC, expand=True)


def card_sprite(text: str, W: int, px: int = 92, fill=CREAM, colour=INK, accent=RED, label: str = "",
                label_px: int = 60, max_frac: float = 0.82) -> Image.Image:
    lines = rich_lines(text)
    f = fit_font(lines, px * SS, W * max_frac * SS - 100 * SS)
    lf = font(label_px * SS) if label else None
    tw = max(sum(f.getlength(s) for s, _ in ln) for ln in lines)
    if lf:
        lf = fit_font(rich_lines(label), label_px * SS, W * max_frac * SS - 100 * SS)
        tw = max(tw, lf.getlength(label.replace("*", "")))
    pad = 46 * SS
    th = len(lines) * f.size * 1.12 + (lf.size * 1.4 if lf else 0)
    w, h = int(tw + 2 * pad), int(th + 2 * pad - f.size * 0.12)
    img = Image.new("RGBA", (w + 20 * SS, h + 26 * SS), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    r = 38 * SS
    seed = zlib.crc32((text + label).encode())
    paper(d, (10 * SS, 8 * SS, w + 10 * SS, h + 8 * SS), seed, fill=fill)
    cx = 10 * SS + w / 2
    draw_rich(d, lines, f, cx, 8 * SS + pad - f.size * 0.12, colour, accent)
    if lf:
        draw_rich(d, rich_lines(label), lf, cx, 8 * SS + pad + len(lines) * f.size * 1.12 + lf.size * 0.2,
                  colour, accent)
    return tilt(img, seed)


def place(canvas: Image.Image, sprite: Image.Image, cx: float, cy: float, scale: float, alpha: float) -> None:
    if alpha <= 0.01 or scale <= 0.01:
        return
    w, h = max(1, int(sprite.width * scale / SS)), max(1, int(sprite.height * scale / SS))
    s = sprite.resize((w, h), Image.LANCZOS)
    if alpha < 0.999:
        a = s.getchannel("A").point(lambda v: int(v * alpha))
        s.putalpha(a)
    canvas.alpha_composite(s, (int(cx - w / 2), int(cy - h / 2)))


# ------------------------------------------------------------------ traffic model
@functools.lru_cache(maxsize=None)
def ov_run(n: int = 22, headway: float = 2.0, a: float = 1.0, t_end: float = 220.0, dt: float = 0.05):
    """Optimal-velocity model (Bando et al. 1995) on a ring. Returns positions, speeds, ring length.

    A ring of evenly spaced cars at this density is unstable: a tiny wobble grows until a
    stop-and-go wave forms, the mechanism the 2008 ring-road experiment demonstrated."""
    L = n * headway
    x = np.arange(n) * headway
    x[0] += 0.15  # the tiny wobble
    v = np.full(n, math.tanh(headway - 2) + math.tanh(2))
    xs, vs = [], []
    for k in range(int(t_end / dt)):
        h = (np.roll(x, -1) - x) % L
        v += a * (np.tanh(h - 2) + math.tanh(2) - v) * dt
        v = np.maximum(v, 0)
        x = x + v * dt
        if k % 4 == 0:
            xs.append(x.copy())
            vs.append(v.copy())
    return np.array(xs), np.array(vs), L


def car_colour(v: float) -> tuple:
    return RED if v < 0.45 else SAND


def panel(W: int, Hp: int, title: str, wfrac: float = 0.8, title_px: int = 58):
    w = int(W * wfrac)
    img = Image.new("RGBA", (w * SS, Hp * SS), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    paper(d, (8 * SS, 6 * SS, w * SS - 8 * SS, Hp * SS - 16 * SS), zlib.crc32(title.encode()))
    lines = rich_lines(title)
    f = fit_font(lines, title_px * SS, (w - 120) * SS)
    draw_rich(d, lines, f, w * SS / 2, 34 * SS)
    return img, d, w, f.size * len(lines) * 1.12 + 40 * SS


def ring_frame(W: int, title: str, mode: str, p: float) -> Image.Image:
    """p in [0, 1]: progress through the overlay. 'even' = steady cruising, 'jam' = the wave forms."""
    xs, vs, L = ov_run()
    n_steps = len(xs)
    # snapshots are 0.2 model-seconds apart. With these settings the first brake lights show at
    # about 55 s and a car first stops at about 90 s.
    if mode == "even":
        k = int(p * 60)  # 0-12 s: still smooth
    else:
        k = int(60 + (min(n_steps - 1, 560) - 60) * p ** 1.3)  # 12-112 s: the wobble becomes a jam
    Hp = int(W * 0.56)
    img, d, w, top = panel(W, Hp, title, 0.62)
    cx, cy = w * SS / 2, top + (Hp * SS - 16 * SS - top) / 2
    R = min(w * SS * 0.36, (Hp * SS - top) * 0.36)
    d.ellipse((cx - R - 32 * SS, cy - R - 32 * SS, cx + R + 32 * SS, cy + R + 32 * SS), fill=(70, 62, 58))
    d.ellipse((cx - R + 32 * SS, cy - R + 32 * SS, cx + R - 32 * SS, cy + R - 32 * SS), fill=(150, 190, 110))
    for x, v in zip(xs[k], vs[k]):
        ang = 2 * math.pi * (x % L) / L - math.pi / 2
        px, py = cx + R * math.cos(ang), cy + R * math.sin(ang)
        r = 24 * SS
        d.ellipse((px - r, py - r, px + r, py + r), fill=car_colour(v), outline=INK, width=3 * SS)
    return img


def wave_frame(W: int, title: str, p: float) -> Image.Image:
    xs, vs, L = ov_run()
    k = min(len(xs) - 1, int(650 + p * 350))  # 130-200 s: the jam exists; watch it travel backwards
    Hp = int(W * 0.4)
    img, d, w, top = panel(W, Hp, title, 0.86)
    x0, x1 = 70 * SS, w * SS - 70 * SS
    lane_y = top + (Hp * SS - 16 * SS - top) * 0.33
    d.rounded_rectangle((x0 - 20 * SS, lane_y - 40 * SS, x1 + 20 * SS, lane_y + 40 * SS), 30 * SS,
                        fill=(70, 62, 58))
    for x, v in zip(xs[k], vs[k]):
        px = x0 + (x1 - x0) * (x % L) / L
        d.rounded_rectangle((px - 21 * SS, lane_y - 20 * SS, px + 21 * SS, lane_y + 20 * SS), 10 * SS,
                            fill=car_colour(v), outline=INK, width=3 * SS)
    f = font(50 * SS)
    ay = lane_y + 110 * SS
    arrow(d, (x0 + 40 * SS, ay), (x0 + 330 * SS, ay), INK)
    d.text((x0 + 360 * SS, ay - 30 * SS), "cars", font=f, fill=INK)
    arrow(d, (x1 - 40 * SS, ay), (x1 - 330 * SS, ay), RED)
    jw = f.getlength("jam")
    d.text((x1 - 360 * SS - jw, ay - 30 * SS), "jam", font=f, fill=RED)
    return img


# ------------------------------------------------------------------ visual field (blind spot)
# Right eye's visual field, drawn to scale. The blind spot is centred about 15 degrees to the
# temporal side of fixation and 1.5 degrees below it, roughly 5.5 degrees wide and 7.5 high
# (MIL-STD-1472F figures); the full moon is about 0.5 degrees across.
BS_X, BS_Y, BS_W, BS_H, MOON = 15.0, -1.5, 5.5, 7.5, 0.5
FIELD_X = (-6.0, 22.0)  # degrees shown, left to right


def field_frame(W: int, title: str, mode: str, p: float) -> Image.Image:
    """mode 'test': cross + red dot, the dot fades away (it sits in the blind spot).
    'moons': the blind spot outlined with full moons to scale inside it.
    'fill': a striped field with a hole at the blind spot that fills in with the stripes."""
    Hp = int(W * 0.62)
    img, d, w, top = panel(W, Hp, title, 0.9, title_px=84)
    x0, x1 = 60 * SS, w * SS - 60 * SS
    # the moons view zooms in on the blind spot so the moons are big enough to count
    span = (BS_X - 5.0, BS_X + 5.0) if mode == "moons" else FIELD_X
    deg = (x1 - x0) / (span[1] - span[0])
    y_mid = top + (Hp * SS - 16 * SS - top) * 0.52
    box_top, box_bot = top + 6 * SS, Hp * SS - 40 * SS
    if mode == "moons":  # fit the whole blind spot, centred in the panel
        deg = min(deg, (box_bot - box_top) * 0.9 / BS_H)
        y_mid = (box_top + box_bot) / 2 + BS_Y * deg
        fx = lambda a: (x0 + x1) / 2 + (a - BS_X) * deg
    else:
        fx = lambda a: x0 + (a - span[0]) * deg
    fy = lambda e: y_mid - e * deg
    bx, by = fx(BS_X), fy(BS_Y)
    rx, ry = BS_W / 2 * deg, BS_H / 2 * deg
    if mode == "fill":
        stripe = 2.0 * deg
        k = 0
        y = box_top
        while y < box_bot:
            d.rectangle((x0, y, x1, min(y + stripe / 2, box_bot)), fill=SAND if k % 2 == 0 else (150, 190, 110))
            y += stripe / 2
            k += 1
        hole = max(0.0, 1.0 - max(0.0, p - 0.3) / 0.4)  # the hole shows, then closes
        if hole > 0.01:
            d.ellipse((bx - rx * hole, by - ry * hole, bx + rx * hole, by + ry * hole), fill=(40, 34, 30))
    # fixation cross
    c, t = 0.9 * deg, 7 * SS
    cx0, cy0 = fx(0), fy(0)
    if mode != "moons":
        d.rectangle((cx0 - c, cy0 - t, cx0 + c, cy0 + t), fill=INK)
        d.rectangle((cx0 - t, cy0 - c, cx0 + t, cy0 + c), fill=INK)
    if mode in ("test", "moons"):
        dash = 8
        for i in range(0, 360, dash * 2):
            d.arc((bx - rx, by - ry, bx + rx, by + ry), i, i + dash, fill=INK, width=6 * SS)
    if mode == "test":
        a = max(0.0, 1.0 - max(0.0, p - 0.35) / 0.3)
        r = 0.9 * deg
        if a > 0.01:
            col = tuple(int(CREAM[i] + (RED[i] - CREAM[i]) * a) for i in range(3))
            d.ellipse((bx - r, by - r, bx + r, by + r), fill=col)
    if mode == "moons":
        n = min(int(BS_W / MOON), max(1, int(1 + p * 1.6 * BS_W / MOON)))
        mr = MOON / 2 * deg
        left = bx - (BS_W / MOON) * mr
        for i in range(n):
            mx = left + mr + i * 2 * mr
            d.ellipse((mx - mr, by - mr, mx + mr, by + mr), fill=(250, 240, 200), outline=INK, width=2 * SS)
    if mode != "moons":
        lf = font(56 * SS)
        lab = "look here"
        d.text((cx0 - lf.getlength(lab) / 2, cy0 + c + 14 * SS), lab, font=lf, fill=INK)
    return img


def arrow(d, a, b, colour, width=12 * SS, head=30 * SS):
    (ax, ay), (bx, by) = a, b
    ang = math.atan2(by - ay, bx - ax)
    ex, ey = bx - head * 0.8 * math.cos(ang), by - head * 0.8 * math.sin(ang)
    d.line((ax, ay, ex, ey), fill=colour, width=width)
    pts = [(bx, by)] + [(bx - head * math.cos(ang + s * 0.5), by - head * math.sin(ang + s * 0.5)) for s in (1, -1)]
    d.polygon(pts, fill=colour)


# ------------------------------------------------------------------ overlay elements
class Element:
    def __init__(self, spec: dict, t0: float, W: int, H: int):
        self.s, self.t0, self.W, self.H = spec, t0, W, H
        self.dur = float(spec.get("dur", 3.0))
        self.cy = float(spec.get("y", 0.22)) * H

    def active(self, t: float) -> bool:
        return self.t0 <= t <= self.t0 + self.dur

    def draw(self, canvas: Image.Image, t: float, y_off: int) -> None:
        typ, lt = self.s["type"], t - self.t0
        cx, cy = self.W / 2, self.cy - y_off
        if typ == "card":
            place(canvas, self._sprite(self.s["text"]), cx, cy, *envelope(lt, self.dur))
        elif typ == "stat":
            k = ease_out_back(lt / 0.8) if lt < 0.8 else 1.0
            shown = re.sub(r"\d+", lambda m: str(max(0, round(int(m.group()) * min(k, 1.0)))), self.s["text"])
            sp = self._sprite("*" + shown + "*", px=190, label=self.s.get("label", ""))
            place(canvas, sp, cx, cy, *envelope(lt, self.dur))
        elif typ == "chain":
            self._chain(canvas, lt, cx, cy)
        elif typ in ("ring", "wave", "field"):
            p = min(max(lt / self.dur, 0.0), 1.0)
            title, mode = self.s.get("title", ""), self.s.get("mode", "")
            if typ == "ring":
                img = ring_frame(self.W, title, mode or "jam", p)
            elif typ == "wave":
                img = wave_frame(self.W, title, p)
            else:
                img = field_frame(self.W, title, mode or "test", p)
            scale, alpha = envelope(lt, self.dur)
            place(canvas, img, cx, cy, min(scale, 1.0) if lt > 0.35 else scale, alpha)
        else:
            raise SystemExit(f"unknown overlay type {typ!r}")

    @functools.lru_cache(maxsize=64)
    def _sprite(self, text: str, px: int = 92, label: str = "") -> Image.Image:
        return card_sprite(text, self.W, px=px, label=label)

    def _chain(self, canvas, lt, cx, cy):
        steps, gap = self.s["steps"], float(self.s.get("gap", 1.5))
        n = len(steps)
        aw = int(self.W * 0.05)
        bw = (self.W * 0.94 - aw * (n - 1)) / n
        sprites = []
        for i, st in enumerate(steps):
            last = i == n - 1
            sp = self._sprite_box(st, int(bw), last)
            sprites.append(sp)
        x = cx - (bw * n + aw * (n - 1)) / 2
        d = ImageDraw.Draw(canvas)
        for i, sp in enumerate(sprites):
            si = lt - i * gap
            scale, alpha = envelope(si, self.dur - i * gap)
            place(canvas, sp, x + bw / 2, cy, scale, alpha)
            if i < n - 1:
                ai = lt - (i + 1) * gap + 0.25
                _, a_alpha = envelope(ai, self.dur - (i + 1) * gap + 0.25)
                if a_alpha > 0.05:
                    grow = min(1.0, ai / 0.3)
                    ax0 = x + bw + aw * 0.12
                    ax1 = ax0 + (aw * 0.76) * grow
                    col = tuple(list(INK) + [int(255 * a_alpha)])
                    arrow(d, (ax0, cy), (ax1, cy), col, width=10, head=26)
            x += bw + aw

    @functools.lru_cache(maxsize=16)
    def _sprite_box(self, text: str, bw: int, last: bool) -> Image.Image:
        fill, colour, accent = (RED, CREAM, CREAM) if last else (CREAM, INK, RED)
        return card_sprite(text, bw, px=78, fill=fill,
                           colour=colour, accent=accent, max_frac=0.9)


# ------------------------------------------------------------------ main
def block_spans(manifest: dict, assembly: dict | None) -> dict[int, tuple[float, float]]:
    """{block n: (start, end)} in the final video: 10 s each, or the assembler sidecar's clip lengths."""
    if not assembly:
        return {b["n"]: ((b["n"] - 1) * 10.0, b["n"] * 10.0) for b in manifest["blocks"]}
    spans, t = {}, 0.0
    for b in assembly["per_block"]:
        spans[b["n"]] = (t, t + float(b["clip_s"]))
        t += float(b["clip_s"])
    return spans


def build_elements(manifest: dict, clock: Clock, W: int, H: int, assembly: dict | None = None) -> list[Element]:
    out = []
    spans = block_spans(manifest, assembly)
    for b in manifest["blocks"]:
        block_start, block_end = spans[b["n"]]
        for spec in b.get("overlays", []):
            t0 = clock.at(spec["at"], after=block_start) + float(spec.get("delay", 0.0))
            spec = dict(spec)
            if spec.get("dur") == "rest":  # hold until just before the scene cut
                spec["dur"] = block_end - 0.2 - t0
            elif "until" in spec:  # hold until the narration reaches this phrase
                spec["dur"] = clock.at(spec["until"], after=t0) - 0.1 - t0
            out.append(Element(spec, t0, W, H))
    return out


def probe(path: str) -> tuple[int, int, float, float]:
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                        "stream=width,height,r_frame_rate:format=duration", "-of", "json", path],
                       capture_output=True, text=True, check=True)
    j = json.loads(r.stdout)
    s = j["streams"][0]
    num, den = s["r_frame_rate"].split("/")
    return s["width"], s["height"], float(num) / float(den), float(j["format"]["duration"])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("manifest")
    ap.add_argument("captions_json", help="caption timing ({captions: [{text, start, end}]})")
    ap.add_argument("inp")
    ap.add_argument("out")
    ap.add_argument("--still", type=float, action="append", default=[],
                    help="also write OUT.t<sec>.png previews of the overlay band at these times")
    ap.add_argument("--assembly", help="assembler sidecar (final_clean.mp4.assembly.json) when the scenes "
                                       "are not 10 s each, e.g. after trimming dead air")
    args = ap.parse_args()
    manifest = json.load(open(args.manifest))
    cues = json.load(open(args.captions_json))
    cues = cues["captions"] if isinstance(cues, dict) else cues
    W, H, fps, dur = probe(args.inp)
    elements = build_elements(manifest, Clock(cues), W, H,
                              json.load(open(args.assembly)) if args.assembly else None)
    y0, y1 = int(H * BAND[0]) // 2 * 2, int(H * BAND[1]) // 2 * 2
    bh = y1 - y0
    for el in elements:
        print(json.dumps({"type": el.s["type"], "start": round(el.t0, 2), "dur": el.dur}), flush=True)
    for t in args.still:
        c = Image.new("RGBA", (W, bh), (0, 0, 0, 0))
        for el in elements:
            if el.active(t):
                el.draw(c, t, y0)
        c.save(f"{args.out}.t{t:.1f}.png")
    if args.still:
        return 0
    blank = bytes(W * bh * 4)
    cmd = ["ffmpeg", "-v", "error", "-y", "-i", args.inp, "-f", "rawvideo", "-pix_fmt", "rgba", "-s", f"{W}x{bh}",
           "-r", f"{fps}", "-i", "pipe:0", "-filter_complex", f"[0:v][1:v]overlay=0:{y0}:format=auto:shortest=1,"
           "format=yuv420p[v]", "-map", "[v]", "-map", "0:a?", "-c:v", "libx264", "-preset", "medium", "-crf", "17",
           "-c:a", "copy", "-movflags", "+faststart", args.out]
    ff = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    n = int(round(dur * fps)) + 2
    for i in range(n):
        t = i / fps
        live = [el for el in elements if el.active(t)]
        if not live:
            ff.stdin.write(blank)
            continue
        c = Image.new("RGBA", (W, bh), (0, 0, 0, 0))
        for el in live:
            el.draw(c, t, y0)
        ff.stdin.write(c.tobytes())
    ff.stdin.close()
    return ff.wait()


if __name__ == "__main__":
    sys.exit(main())
