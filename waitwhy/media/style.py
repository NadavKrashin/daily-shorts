"""Brand drawing kit for deterministic motion graphics (Pillow): palette, fonts, easing, shapes, text."""
from __future__ import annotations

import functools
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

FONT_DIRS = [Path("/usr/share/fonts/opentype/inter"), Path("/usr/share/fonts/truetype/inter"),
             Path("/usr/share/fonts/truetype/dejavu")]
FALLBACKS = {"Inter-Bold": "DejaVuSans-Bold.ttf", "Inter-Medium": "DejaVuSans.ttf",
             "Inter-ExtraBold": "DejaVuSans-Bold.ttf", "Inter-Black": "DejaVuSans-Bold.ttf"}


def hex_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def mix(a, b, t: float):
    t = max(0.0, min(1.0, t))
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(len(a)))


@functools.lru_cache(maxsize=64)
def font(name: str = "Inter-Bold", size: int = 64) -> ImageFont.FreeTypeFont:
    for d in FONT_DIRS:
        for ext in (".otf", ".ttf"):
            p = d / f"{name}{ext}"
            if p.exists():
                return ImageFont.truetype(str(p), size)
    for d in FONT_DIRS:
        p = d / FALLBACKS.get(name, "DejaVuSans-Bold.ttf")
        if p.exists():
            return ImageFont.truetype(str(p), size)
    return ImageFont.load_default(size)


def font_path(name: str = "Inter-Bold") -> str:
    f = font(name, 20)
    return getattr(f, "path", "")


# ---------------------------------------------------------------- easing
def clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def ease_out_cubic(x: float) -> float:
    x = clamp01(x)
    return 1 - (1 - x) ** 3


def ease_in_out(x: float) -> float:
    x = clamp01(x)
    return 3 * x * x - 2 * x * x * x


def ease_out_back(x: float, s: float = 1.6) -> float:
    x = clamp01(x)
    return 1 + (s + 1) * (x - 1) ** 3 + s * (x - 1) ** 2


def pulse(t: float, hz: float = 1.0) -> float:
    return 0.5 + 0.5 * math.sin(2 * math.pi * hz * t)


# ---------------------------------------------------------------- palette
class Palette:
    def __init__(self, cfg_palette: dict | None = None):
        p = {"background": "#0F172A", "surface": "#1E293B", "primary": "#38BDF8", "accent": "#FACC15",
             "warning": "#F97316", "danger": "#EF4444", "success": "#22C55E", "text": "#F8FAFC",
             "muted": "#94A3B8", "smooth": "#A78BFA", "grass": "#14532D", "asphalt": "#334155"}
        p.update(cfg_palette or {})
        for k, v in p.items():
            setattr(self, k, hex_rgb(v))

    def speed_color(self, v_kmh: float, vmax: float = 35.0):
        """Stopped = red, crawling = orange/yellow, free flow = green."""
        x = clamp01(v_kmh / vmax)
        if x < 0.5:
            return mix(self.danger, self.accent, x / 0.5)
        return mix(self.accent, self.success, (x - 0.5) / 0.5)


# ---------------------------------------------------------------- backgrounds / shapes
@functools.lru_cache(maxsize=16)
def vertical_gradient(w: int, h: int, top: tuple, bottom: tuple) -> Image.Image:
    grad = Image.linear_gradient("L").resize((w, h))
    a = Image.new("RGB", (w, h), top)
    b = Image.new("RGB", (w, h), bottom)
    return Image.composite(b, a, grad)


@functools.lru_cache(maxsize=16)
def vignette(w: int, h: int, strength: int = 140) -> Image.Image:
    small = Image.radial_gradient("L").resize((w // 4, h // 4))
    small = small.point(lambda v: int(max(0, v - 90) * strength / 165))
    return small.resize((w, h), Image.BILINEAR)


def apply_vignette(img: Image.Image, strength: int = 140) -> Image.Image:
    black = Image.new("RGB", img.size, (0, 0, 0))
    return Image.composite(black, img, vignette(img.width, img.height, strength))


def soft_shadow(size: tuple[int, int], radius: int, blur: int = 12, opacity: int = 110) -> Image.Image:
    w, h = size
    pad = blur * 3
    m = Image.new("L", (w + 2 * pad, h + 2 * pad), 0)
    ImageDraw.Draw(m).rounded_rectangle([pad, pad, pad + w, pad + h], radius=radius, fill=opacity)
    return m.filter(ImageFilter.GaussianBlur(blur))


def rounded_panel(img: Image.Image, box, radius=36, fill=(30, 41, 59), shadow=True, outline=None, width=0):
    x0, y0, x1, y1 = [int(v) for v in box]
    if shadow:
        sh = soft_shadow((x1 - x0, y1 - y0), radius, blur=16, opacity=120)
        pad = 48
        img.paste((0, 0, 0), (x0 - pad + 6, y0 - pad + 14), sh)
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([x0, y0, x1, y1], radius=radius, fill=fill, outline=outline, width=width)


def text_center(img: Image.Image, xy, text: str, f: ImageFont.FreeTypeFont, fill, stroke=0, stroke_fill=(0, 0, 0),
                anchor="mm", alpha: float = 1.0, shadow: bool = True):
    if alpha <= 0.01:
        return
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    if shadow:
        d.text((xy[0] + 3, xy[1] + 5), text, font=f, fill=(0, 0, 0, 120), anchor=anchor, stroke_width=stroke,
               stroke_fill=(0, 0, 0, 120))
    d.text(xy, text, font=f, fill=fill + (255,) if len(fill) == 3 else fill, anchor=anchor, stroke_width=stroke,
           stroke_fill=stroke_fill)
    if alpha < 1.0:
        a = layer.getchannel("A").point(lambda v: int(v * alpha))
        layer.putalpha(a)
    img.paste(layer, (0, 0), layer)


def wrap(text: str, f: ImageFont.FreeTypeFont, max_w: int) -> list[str]:
    words, lines, cur = text.split(), [], ""
    for w in words:
        trial = f"{cur} {w}".strip()
        if f.getlength(trial) <= max_w or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def pill(img: Image.Image, center, text: str, f, fg, bg, pad_x=28, pad_y=16, alpha=1.0, scale=1.0):
    if alpha <= 0.01:
        return
    tw = f.getlength(text)
    th = f.size
    w, h = (tw + 2 * pad_x) * scale, (th + 2 * pad_y) * scale
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    cx, cy = center
    d.rounded_rectangle([cx - w / 2 + 4, cy - h / 2 + 8, cx + w / 2 + 4, cy + h / 2 + 8], radius=h / 2, fill=(0, 0, 0, 90))
    d.rounded_rectangle([cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2], radius=h / 2, fill=bg + (255,))
    if scale > 0.3:
        fs = font(Path(getattr(f, "path", "Inter-Bold")).stem, max(8, int(f.size * scale)))
        d.text((cx, cy), text, font=fs, fill=fg + (255,), anchor="mm")
    if alpha < 1:
        layer.putalpha(layer.getchannel("A").point(lambda v: int(v * alpha)))
    img.paste(layer, (0, 0), layer)


def arrow(d: ImageDraw.ImageDraw, p0, p1, fill, width=14, head=36):
    d.line([p0, p1], fill=fill, width=width)
    ang = math.atan2(p1[1] - p0[1], p1[0] - p0[0])
    left = (p1[0] - head * math.cos(ang - 0.45), p1[1] - head * math.sin(ang - 0.45))
    right = (p1[0] - head * math.cos(ang + 0.45), p1[1] - head * math.sin(ang + 0.45))
    d.polygon([p1, left, right], fill=fill)


def arc_arrow(d: ImageDraw.ImageDraw, center, r, a0_deg, a1_deg, fill, width=16, head=40):
    cx, cy = center
    lo, hi = sorted([a0_deg, a1_deg])
    d.arc([cx - r, cy - r, cx + r, cy + r], lo, hi, fill=fill, width=width)
    end = math.radians(a1_deg)
    p1 = (cx + r * math.cos(end), cy + r * math.sin(end))
    direction = 1 if a1_deg > a0_deg else -1
    tang = end + direction * math.pi / 2
    p0 = (p1[0] - 10 * math.cos(tang), p1[1] - 10 * math.sin(tang))
    arrow(d, p0, p1, fill, width=1, head=head)


@functools.lru_cache(maxsize=4096)
def car_sprite(color: tuple, length: int, width: int, angle_q: int, brake: bool, highlight: bool) -> Image.Image:
    """Top-down stylised miniature car (body, roof, windscreen, lights) rotated to angle_q degrees."""
    s = 3  # supersample
    L, W = length * s, width * s
    pad = 10 * s
    im = Image.new("RGBA", (L + 2 * pad, W + 2 * pad), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    body = [pad, pad, pad + L, pad + W]
    if highlight:
        d.rounded_rectangle([pad - 7 * s, pad - 7 * s, pad + L + 7 * s, pad + W + 7 * s], radius=W // 2 + 7 * s,
                            outline=(255, 255, 255, 230), width=4 * s)
    d.rounded_rectangle(body, radius=int(W * 0.38), fill=color + (255,))
    dark = mix(color, (0, 0, 0), 0.35)
    light = mix(color, (255, 255, 255), 0.35)
    # roof
    d.rounded_rectangle([pad + L * 0.30, pad + W * 0.16, pad + L * 0.72, pad + W * 0.84], radius=int(W * 0.25),
                        fill=light + (255,))
    # windscreen (front = +x) and rear window
    d.rounded_rectangle([pad + L * 0.70, pad + W * 0.18, pad + L * 0.80, pad + W * 0.82], radius=int(W * 0.12),
                        fill=(30, 41, 59, 255))
    d.rounded_rectangle([pad + L * 0.20, pad + W * 0.22, pad + L * 0.28, pad + W * 0.78], radius=int(W * 0.1),
                        fill=(30, 41, 59, 230))
    # side shading
    d.rectangle([pad + L * 0.1, pad + W * 0.88, pad + L * 0.9, pad + W * 0.97], fill=dark + (160,))
    # head / tail lights
    d.ellipse([pad + L - 7 * s, pad + 3 * s, pad + L - 1 * s, pad + 9 * s], fill=(255, 251, 220, 255))
    d.ellipse([pad + L - 7 * s, pad + W - 9 * s, pad + L - 1 * s, pad + W - 3 * s], fill=(255, 251, 220, 255))
    tail = (255, 40, 40, 255) if brake else (150, 30, 30, 255)
    d.rectangle([pad, pad + 4 * s, pad + 4 * s, pad + 11 * s], fill=tail)
    d.rectangle([pad, pad + W - 11 * s, pad + 4 * s, pad + W - 4 * s], fill=tail)
    if brake:
        glow = Image.new("RGBA", im.size, (0, 0, 0, 0))
        gd = ImageDraw.Draw(glow)
        gd.ellipse([pad - 18 * s, pad - 6 * s, pad + 10 * s, pad + W + 6 * s], fill=(255, 30, 30, 110))
        glow = glow.filter(ImageFilter.GaussianBlur(9 * s))
        im = Image.alpha_composite(glow, im)
    im = im.resize((im.width // s, im.height // s), Image.LANCZOS)
    return im.rotate(angle_q, resample=Image.BICUBIC, expand=True)


def paste_car(img: Image.Image, center, color, length, width, angle_deg, brake=False, highlight=False, shadow=True):
    q = int(round(angle_deg / 3.0)) * 3 % 360
    spr = car_sprite(tuple(color), int(length), int(width), q, bool(brake), bool(highlight))
    x, y = int(center[0] - spr.width / 2), int(center[1] - spr.height / 2)
    if shadow:
        sh = spr.getchannel("A").point(lambda v: int(v * 0.45)).filter(ImageFilter.GaussianBlur(5))
        img.paste((0, 0, 0), (x + 5, y + 9), sh)
    img.paste(spr, (x, y), spr)
