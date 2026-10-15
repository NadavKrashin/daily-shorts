"""Deterministic scene templates (motion graphics). Each template renders ONE frame for local time ``ctx.t``.

Layout contract for 1080x1920 (keeps text clear of platform UI overlays):
  y 260-470  headline / on-screen text
  y 480-1160 main visual
  y 1170-1220 small tags (e.g. "SIMULATION")
  y 1250-1430 burned-in captions (rendered later by libass)
  y >1440 and right 180 px: kept free of important content (app buttons / description)
"""
from __future__ import annotations

import functools
import math
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from waitwhy.media import style as st
from waitwhy.media import traffic as tr

W, H = 1080, 1920


@dataclass
class FrameCtx:
    t: float
    dur: float
    params: dict
    pal: st.Palette
    on_screen_text: str = ""
    asset_path: Path | None = None
    extras: dict = field(default_factory=dict)

    @property
    def u(self) -> float:  # normalised progress 0..1
        return st.clamp01(self.t / max(self.dur, 1e-6))


TEMPLATES: dict[str, callable] = {}
DESCRIPTIONS: dict[str, str] = {}


def template(name: str, description: str):
    def deco(fn):
        TEMPLATES[name] = fn
        DESCRIPTIONS[name] = description
        return fn
    return deco


# ============================================================== shared pieces
def background(pal: st.Palette) -> Image.Image:
    return st.vertical_gradient(W, H, st.mix(pal.background, (0, 0, 0), 0.25), st.mix(pal.surface, pal.background, 0.3)).copy()


def top_scrim(img: Image.Image, height: int = 620) -> None:
    """Dark gradient behind the headline area so text stays legible over busy visuals."""
    mask = Image.linear_gradient("L").rotate(180).resize((W, height)).point(lambda v: int(v * 0.85))
    img.paste((8, 12, 24), (0, 0), mask)


def headline(img, ctx: FrameCtx, text: str | None = None, y: int = 360, size: int = 74, appear: float = 0.15,
             color=None, scrim: bool = False):
    text = ctx.on_screen_text if text is None else text
    if scrim:
        top_scrim(img)
    if not text:
        return
    f = st.font("Inter-ExtraBold", size)
    lines = st.wrap(text.upper(), f, W - 240)
    k = st.ease_out_back(ctx.t / 0.45) if ctx.t >= appear else 0
    a = st.clamp01((ctx.t - appear) / 0.25)
    for i, line in enumerate(lines[:2]):
        yy = y + i * (size + 14) + (1 - k) * 40
        st.text_center(img, (W / 2, yy), line, f, color or ctx.pal.text, stroke=4, stroke_fill=(10, 15, 30), alpha=a)


def tag(img, ctx: FrameCtx, text: str, y: int = 1192):
    st.pill(img, (W / 2, y), text, st.font("Inter-Bold", 30), ctx.pal.text, st.mix(ctx.pal.surface, (0, 0, 0), 0.2),
            pad_x=22, pad_y=10, alpha=st.clamp01(ctx.t / 0.4))


def fade_edges(img: Image.Image, ctx: FrameCtx, fin: float = 0.0, fout: float = 0.0) -> Image.Image:
    a = 1.0
    if fin > 0:
        a = min(a, st.clamp01(ctx.t / fin))
    if fout > 0:
        a = min(a, st.clamp01((ctx.dur - ctx.t) / fout))
    if a < 1:
        img = Image.blend(Image.new("RGB", img.size, ctx.pal.background), img, a)
    return img


# ============================================================== generic templates
@template("title_card", "Big headline with animated brand shapes. params: headline, subline")
def title_card(ctx: FrameCtx) -> Image.Image:
    img = background(ctx.pal)
    d = ImageDraw.Draw(img)
    for i in range(5):
        r = 160 + 60 * i
        cx = W / 2 + math.sin(ctx.t * 0.6 + i) * 60
        cy = 860 + math.cos(ctx.t * 0.5 + i * 1.3) * 50
        col = st.mix(ctx.pal.primary, ctx.pal.background, 0.75 + 0.04 * i)
        d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=col, width=6)
    headline(img, ctx, ctx.params.get("headline", ctx.on_screen_text), y=800, size=96)
    if ctx.params.get("subline"):
        st.text_center(img, (W / 2, 1040), ctx.params["subline"], st.font("Inter-Medium", 46), ctx.pal.muted,
                       alpha=st.clamp01((ctx.t - 0.5) / 0.4))
    return st.apply_vignette(img, 90)


@template("kinetic_text", "Words pop in line by line. params: lines (list of str)")
def kinetic_text(ctx: FrameCtx) -> Image.Image:
    img = background(ctx.pal)
    lines = ctx.params.get("lines") or [ctx.on_screen_text or ""]
    f = st.font("Inter-ExtraBold", 84)
    for i, line in enumerate(lines[:4]):
        start = i * 0.5
        k = st.ease_out_back((ctx.t - start) / 0.5) if ctx.t >= start else 0
        st.text_center(img, (W / 2, 640 + i * 130 + (1 - k) * 50), line, f,
                       ctx.pal.accent if i == len(lines) - 1 else ctx.pal.text, stroke=4,
                       alpha=st.clamp01((ctx.t - start) / 0.25))
    return st.apply_vignette(img, 90)


@template("big_number", "Counter animating to a value. params: value (float), unit, label, decimals")
def big_number(ctx: FrameCtx) -> Image.Image:
    img = background(ctx.pal)
    v = float(ctx.params.get("value", 0)) * st.ease_out_cubic(ctx.t / 1.2)
    dec = int(ctx.params.get("decimals", 0))
    txt = f"{v:,.{dec}f}{ctx.params.get('unit', '')}"
    st.text_center(img, (W / 2, 820), txt, st.font("Inter-ExtraBold", 190), ctx.pal.accent, stroke=6)
    st.text_center(img, (W / 2, 1010), ctx.params.get("label", ""), st.font("Inter-Bold", 54), ctx.pal.text,
                   alpha=st.clamp01((ctx.t - 0.6) / 0.4))
    headline(img, ctx)
    return st.apply_vignette(img, 90)


@template("end_card", "Brand end card. params: none")
def end_card(ctx: FrameCtx) -> Image.Image:
    img = background(ctx.pal)
    draw_logo(img, ctx, (W / 2, 820), 200 * st.ease_out_back(ctx.t / 0.6))
    name = ctx.extras.get("brand_name", "Wait, Why?")
    st.text_center(img, (W / 2, 1090), name, st.font("Inter-ExtraBold", 96), ctx.pal.text, stroke=4,
                   alpha=st.clamp01((ctx.t - 0.25) / 0.3))
    st.text_center(img, (W / 2, 1185), ctx.extras.get("tagline", ""), st.font("Inter-Medium", 42), ctx.pal.muted,
                   alpha=st.clamp01((ctx.t - 0.5) / 0.3))
    return st.apply_vignette(img, 90)


def draw_logo(img, ctx, center, r):
    if r <= 2:
        return
    d = ImageDraw.Draw(img)
    cx, cy = center
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=ctx.pal.primary)
    d.ellipse([cx - r * 0.82, cy - r * 0.82, cx + r * 0.82, cy + r * 0.82], fill=st.mix(ctx.pal.primary, (0, 0, 0), 0.25))
    st.text_center(img, (cx, cy + r * 0.04), "?", st.font("Inter-Black", max(10, int(r * 1.25))), ctx.pal.accent,
                   shadow=False)


@template("image_kenburns", "AI still image with slow zoom/pan (render_method=ai_image). params: zoom_from, zoom_to, pan")
def image_kenburns(ctx: FrameCtx) -> Image.Image:
    src = _load_cover(str(ctx.asset_path)) if ctx.asset_path else None
    if src is None:
        img = background(ctx.pal)
    else:
        z0, z1 = float(ctx.params.get("zoom_from", 1.0)), float(ctx.params.get("zoom_to", 1.12))
        z = z0 + (z1 - z0) * st.ease_in_out(ctx.u)
        pan = float(ctx.params.get("pan", 0.0))
        cw, ch = W / z, H / z
        x0 = (src.width - cw) / 2 + pan * (src.width - cw) / 2 * (ctx.u - 0.5) * 2
        y0 = (src.height - ch) / 2
        img = src.resize((W, H), Image.LANCZOS, box=(x0, y0, x0 + cw, y0 + ch))
    headline(img, ctx)
    return img


@functools.lru_cache(maxsize=8)
def _load_cover(path: str) -> Image.Image:
    im = Image.open(path).convert("RGB")
    scale = max(W / im.width, H / im.height)
    im = im.resize((int(im.width * scale) + 2, int(im.height * scale) + 2), Image.LANCZOS)
    return im


# ============================================================== traffic: highway (3 lanes, flow = upward)
PPM = 28.0               # pixels per metre on the highway
LANE_PX = 3.5 * PPM
ROAD_X0 = W / 2 - 1.5 * LANE_PX
LANE_SEEDS = (3, 4, 5)


@functools.lru_cache(maxsize=4)
def _trees(seed: int = 7):
    rng = np.random.default_rng(seed)
    pts = []
    for side in (-1, 1):
        for _ in range(26):
            dist = rng.uniform(30, 330)
            y_m = rng.uniform(0, tr.RING_M)
            r = rng.uniform(26, 46)
            pts.append((side, dist, y_m, r))
    return pts


def _lane_sims(regime: str, smoother: bool):
    return [tr.simulate(regime, 300.0, seed=s, smoother_on=0.0 if smoother else None) for s in LANE_SEEDS]


def draw_highway(ctx: FrameCtx, sim_t: float, cam_m: float, regime: str = "jam", smoother: bool = False,
                 highlight_car: tuple[int, int] | None = None, zoom: float = 1.0) -> Image.Image:
    pal = ctx.pal
    img = Image.new("RGB", (W, H), st.mix(pal.grass, (20, 30, 20), 0.2))
    d = ImageDraw.Draw(img)
    ppm = PPM * zoom
    lane_px = 3.5 * ppm
    road_x0 = W / 2 - 1.5 * lane_px
    road_x1 = road_x0 + 3 * lane_px

    def screen_y(pos_m: float) -> float:
        rel = (pos_m - cam_m + tr.RING_M / 2) % tr.RING_M - tr.RING_M / 2
        return H / 2 - rel * ppm

    # scenery (periodic with the ring length so it scrolls consistently)
    for side, dist, y_m, r in _trees():
        y = screen_y(y_m)
        x = W / 2 + side * (1.5 * lane_px + 30 + dist * zoom)
        rr = r * zoom
        if -80 < y < H + 80 and -60 < x < W + 60:
            d.ellipse([x - rr + 8, y - rr + 14, x + rr + 8, y + rr + 14], fill=(10, 30, 15))
            d.ellipse([x - rr, y - rr, x + rr, y + rr], fill=(34, 110, 60))
            d.ellipse([x - rr * 0.55, y - rr * 0.7, x + rr * 0.25, y + rr * 0.1], fill=(60, 150, 85))
    # road + shoulders
    d.rectangle([road_x0 - 26 * zoom, 0, road_x1 + 26 * zoom, H], fill=(71, 85, 105))
    d.rectangle([road_x0, 0, road_x1, H], fill=pal.asphalt)
    d.rectangle([road_x0 - 6 * zoom, 0, road_x0, H], fill=(226, 232, 240))
    d.rectangle([road_x1, 0, road_x1 + 6 * zoom, H], fill=(226, 232, 240))
    dash, gapm = 3.0, 9.0
    for k in (1, 2):
        x = road_x0 + k * lane_px
        start = math.floor((cam_m - 60) / (dash + gapm)) * (dash + gapm)
        m = start
        while m < cam_m + 60:
            y0, y1 = screen_y(m + dash), screen_y(m)
            if y1 > -20 and y0 < H + 20:
                d.rectangle([x - 3 * zoom, y0, x + 3 * zoom, y1], fill=(226, 232, 240))
            m += dash + gapm
    # cars
    sims = _lane_sims(regime, smoother)
    for lane, sim in enumerate(sims):
        xs, vs, accs = sim.at(sim_t)
        x_center = road_x0 + (lane + 0.5) * lane_px
        for i in range(tr.N_CARS):
            y = screen_y(xs[i] + tr.CAR_M / 2)
            if -80 < y < H + 80:
                is_hl = highlight_car == (lane, i)
                is_smooth = smoother and i == 0
                color = pal.smooth if is_smooth else (pal.primary if is_hl else pal.speed_color(vs[i] * 3.6))
                st.paste_car(img, (x_center, y), color, tr.CAR_M * ppm, 2.0 * ppm, 90,
                             brake=accs[i] < -0.4, highlight=is_hl or is_smooth)
    return img


def _jam_position(sim: tr.RingSim, t: float) -> float:
    xs, vs, _ = sim.at(t)
    # smooth estimate: circular mean of slow cars' positions weighted by slowness
    w = np.clip(10 - vs * 3.6 / 2, 0, None) + 1e-3
    ang = xs / tr.RING_M * 2 * np.pi
    c, s = (w * np.cos(ang)).sum(), (w * np.sin(ang)).sum()
    return (math.atan2(s, c) % (2 * math.pi)) / (2 * math.pi) * tr.RING_M


@functools.lru_cache(maxsize=8)
def _jam_track(seed: int, t0: float, t1: float, step: float = 0.5):
    sim = tr.simulate("jam", 300.0, seed=seed)
    ts = np.arange(t0, t1 + step, step)
    raw = np.array([_jam_position(sim, t) for t in ts])
    unw = np.unwrap(raw / tr.RING_M * 2 * np.pi) * tr.RING_M / (2 * np.pi)
    k = 9
    sm = np.convolve(np.pad(unw, k // 2, mode="edge"), np.ones(k) / k, mode="valid")
    return ts, sm


@template("highway_jam", "3-lane highway (flow upward), stop-and-go jam from IDM sim; camera tracks the jam. "
                         "params: sim_start, push_in")
def highway_jam(ctx: FrameCtx) -> Image.Image:
    t0 = float(ctx.params.get("sim_start", 255.0))
    ts, track = _jam_track(LANE_SEEDS[1], t0, t0 + 40)
    sim_t = t0 + ctx.t
    cam = float(np.interp(sim_t, ts, track)) + 6
    zoom = 1.0 + float(ctx.params.get("push_in", 0.08)) * st.ease_in_out(ctx.u)
    img = draw_highway(ctx, sim_t, cam, zoom=zoom)
    img = st.apply_vignette(img, 120)
    headline(img, ctx, y=340, scrim=True)
    tag(img, ctx, "SIMULATION")
    return fade_edges(img, ctx, fin=0.25)


@template("highway_flyover", "Camera flies forward from the jam to its empty front. params: sim_start, fly_m")
def highway_flyover(ctx: FrameCtx) -> Image.Image:
    t0 = float(ctx.params.get("sim_start", 255.0))
    prev_dur = float(ctx.params.get("prev_dur", 4.0))
    ts, track = _jam_track(LANE_SEEDS[1], t0, t0 + 60)
    sim_t = t0 + prev_dur + ctx.t
    base = float(np.interp(sim_t, ts, track)) + 6
    cam = base + float(ctx.params.get("fly_m", 48)) * st.ease_in_out(ctx.t / max(1.0, ctx.dur * 0.7))
    img = draw_highway(ctx, sim_t, cam)
    img = st.apply_vignette(img, 120)
    top_scrim(img)
    items = ctx.params.get("checks", ["NO ACCIDENT", "NO ROADWORK"])
    f = st.font("Inter-ExtraBold", 54)
    for i, label in enumerate(items):
        start = ctx.dur * 0.45 + i * 0.6
        if ctx.t >= start:
            k = st.ease_out_back((ctx.t - start) / 0.4)
            st.pill(img, (W / 2, 330 + i * 120), label, f, ctx.pal.text, ctx.pal.danger, alpha=st.clamp01(k),
                    scale=max(0.01, k))
    q_start = ctx.dur * 0.2
    if ctx.t > q_start:
        k = st.ease_out_back((ctx.t - q_start) / 0.5)
        st.text_center(img, (W - 230, 760), "?", st.font("Inter-Black", int(220 * max(k, 0.05))), ctx.pal.accent,
                       stroke=6, stroke_fill=(10, 15, 30), alpha=st.clamp01(k))
    tag(img, ctx, "SIMULATION")
    return img


@template("highway_flow", "Smooth flow with a highlighted purple car keeping a gap. params: sim_start, show_gap")
def highway_flow(ctx: FrameCtx) -> Image.Image:
    t0 = float(ctx.params.get("sim_start", 220.0))
    sim_t = t0 + ctx.t
    sim = _lane_sims("jam", True)[1]
    xs, _, _ = sim.at(sim_t)
    cam = float(xs[0]) + 10
    img = draw_highway(ctx, sim_t, cam, smoother=True)
    if ctx.params.get("show_gap", True):
        d = ImageDraw.Draw(img)
        lead = xs[1]
        y_smooth = H / 2 - ((xs[0] + tr.CAR_M) - cam) * PPM
        rel = (lead - cam + tr.RING_M / 2) % tr.RING_M - tr.RING_M / 2
        y_lead = H / 2 - rel * PPM
        xb = ROAD_X0 + 1.5 * LANE_PX + 1.5 * LANE_PX + 46
        k = st.ease_out_cubic((ctx.t - 0.4) / 0.6)
        if k > 0 and y_lead < y_smooth:
            col = ctx.pal.smooth
            d.line([(xb, y_smooth), (xb, y_smooth + (y_lead - y_smooth) * k)], fill=col, width=10)
            d.line([(xb - 22, y_smooth), (xb + 22, y_smooth)], fill=col, width=10)
            if k >= 1:
                d.line([(xb - 22, y_lead), (xb + 22, y_lead)], fill=col, width=10)
            st.pill(img, (xb + 10, (y_smooth + y_lead) / 2), "GAP", st.font("Inter-ExtraBold", 40), ctx.pal.text,
                    col, alpha=k)
    img = st.apply_vignette(img, 110)
    headline(img, ctx, y=340, color=ctx.pal.text, scrim=True)
    # brand end card fades in over the last ``end_card_s`` seconds
    ec = float(ctx.params.get("end_card_s", 0))
    if ec > 0 and ctx.t > ctx.dur - ec:
        sub = FrameCtx(t=ctx.t - (ctx.dur - ec), dur=ec, params={}, pal=ctx.pal, extras=ctx.extras)
        card = end_card(sub)
        img = Image.blend(img, card, st.ease_in_out((ctx.t - (ctx.dur - ec)) / 0.4))
    else:
        tag(img, ctx, "SIMULATION")
    return img


# ============================================================== traffic: ring road
RING_C = (W / 2, 840)
RING_R = 330


def _ring_pos(x_m: float, r: float = RING_R, c=RING_C):
    # cars drive counter-clockwise on screen; 0 m at the bottom of the ring
    ang = math.pi / 2 - x_m / tr.RING_M * 2 * math.pi
    return c[0] + r * math.cos(ang), c[1] + r * math.sin(ang), ang


def draw_ring(img, ctx: FrameCtx, sim: tr.RingSim, sim_t: float, *, center=RING_C, r=RING_R, scale=1.0,
              highlight: int | None = None, smooth_car: int | None = None, reveal: float = 1.0,
              cars_shown: int = tr.N_CARS, label_speed: bool = False):
    pal = ctx.pal
    d = ImageDraw.Draw(img)
    track_w = 74 * scale
    cx, cy = center
    # infield + track
    d.ellipse([cx - r - track_w / 2 - 14, cy - r - track_w / 2 - 14, cx + r + track_w / 2 + 14, cy + r + track_w / 2 + 14],
              fill=(71, 85, 105))
    sweep = 360 * reveal
    d.pieslice([cx - r - track_w / 2, cy - r - track_w / 2, cx + r + track_w / 2, cy + r + track_w / 2], 90, 90 + sweep,
               fill=pal.asphalt)
    d.ellipse([cx - r + track_w / 2, cy - r + track_w / 2, cx + r - track_w / 2, cy + r - track_w / 2],
              fill=st.mix(pal.grass, (0, 0, 0), 0.15))
    if reveal >= 1:
        for k in range(36):
            a0 = k * 10
            d.arc([cx - r, cy - r, cx + r, cy + r], a0, a0 + 4, fill=(203, 213, 225), width=max(2, int(3 * scale)))
    xs, vs, accs = sim.at(sim_t)
    for i in range(min(cars_shown, tr.N_CARS)):
        x, y, ang = _ring_pos(xs[i] + tr.CAR_M / 2, r, center)
        heading = -math.degrees(ang) - 90  # tangent for counter-clockwise motion
        if i == highlight:
            col = pal.primary
        elif i == smooth_car:
            col = pal.smooth
        else:
            col = pal.speed_color(vs[i] * 3.6)
        st.paste_car(img, (x, y), col, tr.CAR_M * 13.0 * scale, 2.0 * 13.0 * scale, heading, brake=accs[i] < -0.4,
                     highlight=i in (highlight, smooth_car))
    if label_speed:
        avg = float(vs.mean() * 3.6)
        st.text_center(img, (cx, cy - 30 * scale), f"{avg:0.0f}", st.font("Inter-ExtraBold", int(120 * scale)), pal.text,
                       stroke=3)
        st.text_center(img, (cx, cy + 60 * scale), "km/h avg", st.font("Inter-Bold", int(40 * scale)), pal.muted)
    return xs, vs


@template("ring_road", "22-car ring road (Sugiyama 2008 setup) from IDM sim. params: mode intro|steady|perturb|jam, "
                       "sim_start, speedup")
def ring_road(ctx: FrameCtx) -> Image.Image:
    mode = ctx.params.get("mode", "steady")
    sim = tr.simulate("jam", 300.0)
    speedup = float(ctx.params.get("speedup", 1.0))
    sim_t = float(ctx.params.get("sim_start", 0.0)) + ctx.t * speedup
    img = background(ctx.pal)
    if mode == "intro":
        reveal = st.ease_in_out(ctx.t / 1.0)
        shown = int(tr.N_CARS * st.clamp01((ctx.t - 0.8) / 1.4))
        draw_ring(img, ctx, sim, sim_t, reveal=reveal, cars_shown=shown)
        f = st.font("Inter-ExtraBold", 50)
        if ctx.t > 1.2:
            st.pill(img, (W / 2 - 210, 380), "22 CARS", f, ctx.pal.background, ctx.pal.accent,
                    alpha=st.clamp01((ctx.t - 1.2) / 0.3))
        if ctx.t > 1.8:
            st.pill(img, (W / 2 + 200, 380), "230 M TRACK", f, ctx.pal.background, ctx.pal.primary,
                    alpha=st.clamp01((ctx.t - 1.8) / 0.3))
        tag(img, ctx, "SUGIYAMA ET AL. 2008  ·  RE-CREATED IN SIMULATION")
    elif mode == "steady":
        draw_ring(img, ctx, sim, sim_t, label_speed=True)
        headline(img, ctx, y=360)
        tag(img, ctx, "SIMULATION")
    elif mode == "perturb":
        zoom_k = st.ease_in_out(ctx.t / 2.0)
        xs, vs = draw_ring(img, ctx, sim, sim_t, highlight=0)
        x, y, _ = _ring_pos(xs[0] + tr.CAR_M / 2)
        if ctx.t > 0.6:
            st.pill(img, (min(max(x, 220), W - 260), min(max(y - 110, 600), 1100)), f"{vs[0] * 3.6:0.0f} km/h",
                    st.font("Inter-ExtraBold", 44), ctx.pal.background, ctx.pal.primary,
                    alpha=st.clamp01((ctx.t - 0.6) / 0.3))
        headline(img, ctx, y=360)
        tag(img, ctx, "SIMULATION")
        if zoom_k > 0:
            s = 1 + 0.12 * zoom_k
            cw, ch = W / s, H / s
            ox = (x - W / 2) * 0.3 * zoom_k
            bx0 = min(max(0.0, W / 2 - cw / 2 + ox), W - cw)
            by0 = min(max(0.0, 840 - ch * 840 / H), H - ch)
            img = img.resize((W, H), Image.LANCZOS, box=(bx0, by0, bx0 + cw, by0 + ch))
    elif mode == "jam":
        xs, vs = draw_ring(img, ctx, sim, sim_t)
        d = ImageDraw.Draw(img)
        k = st.clamp01((ctx.t - 0.5) / 0.6)
        if k > 0:
            jam_m = _jam_position(sim, sim_t)
            _, _, jang = _ring_pos(jam_m)
            jdeg = math.degrees(jang)
            r_out = RING_R + 105
            # cars move counter-clockwise on screen => decreasing screen angle; the jam moves the other way
            st.arc_arrow(d, RING_C, r_out, jdeg + 8, jdeg + 8 + 55 * k, ctx.pal.danger, width=16, head=40)
            jx, jy, _ = _ring_pos(jam_m, r_out + 70)
            st.pill(img, (min(max(jx, 200), W - 260), jy), "JAM", st.font("Inter-ExtraBold", 40), ctx.pal.text,
                    ctx.pal.danger, alpha=k)
            st.arc_arrow(d, RING_C, RING_R - 120, jdeg + 180, jdeg + 180 - 55 * k, ctx.pal.success, width=14, head=36)
            cx2, cy2, _ = _ring_pos(jam_m + tr.RING_M / 2, RING_R - 200)
            st.pill(img, (cx2, cy2), "CARS", st.font("Inter-ExtraBold", 36), ctx.pal.background, ctx.pal.success,
                    alpha=k)
        headline(img, ctx, y=340)
        tag(img, ctx, f"SIMULATION  ·  {speedup:g}× SPEED")
    return img


@template("ring_compare", "Two rings side by side: human drivers only vs one smooth driver. params: sim_start, speedup")
def ring_compare(ctx: FrameCtx) -> Image.Image:
    img = background(ctx.pal)
    speedup = float(ctx.params.get("speedup", 1.0))
    sim_t = float(ctx.params.get("sim_start", 230.0)) + ctx.t * speedup
    base = tr.simulate("jam", 300.0)
    smooth = tr.simulate("jam", 300.0, smoother_on=0.0, smoother_car=11)
    r, sc = 205, 0.62
    left, right = (W * 0.27, 850), (W * 0.73, 850)
    _, v1 = draw_ring(img, ctx, base, sim_t, center=left, r=r, scale=sc)
    _, v2 = draw_ring(img, ctx, smooth, sim_t, center=right, r=r, scale=sc, smooth_car=11)
    f = st.font("Inter-ExtraBold", 38)
    st.pill(img, (left[0], 545), "ALL HUMAN", f, ctx.pal.text, st.mix(ctx.pal.danger, (0, 0, 0), 0.15))
    st.pill(img, (right[0], 545), "+1 SMOOTH CAR", f, ctx.pal.background, ctx.pal.smooth)
    sf = st.font("Inter-Bold", 40)
    st.text_center(img, (left[0], 1120), f"slowest: {v1.min() * 3.6:0.0f} km/h", sf, ctx.pal.text)
    st.text_center(img, (right[0], 1120), f"slowest: {v2.min() * 3.6:0.0f} km/h", sf, ctx.pal.text)
    headline(img, ctx, y=340)
    tag(img, ctx, "SIMULATION  ·  SAME DRIVERS, SAME TRACK", y=1200)
    return img


@template("brake_chain", "Column of cars; each brakes later and harder (illustrative). params: n")
def brake_chain(ctx: FrameCtx) -> Image.Image:
    img = background(ctx.pal)
    d = ImageDraw.Draw(img)
    n = int(ctx.params.get("n", 5))
    lane_x = 400
    d.rounded_rectangle([lane_x - 70, 470, lane_x + 70, 1170], radius=30, fill=ctx.pal.asphalt)
    delay = 0.75
    for i in range(n):  # i=0 is the front car (top)
        start = 0.5 + i * delay
        k = st.clamp01((ctx.t - start) / 0.5)
        strength = 1.0 + 0.45 * i
        y = 540 + i * 140 + 10 * math.sin(ctx.t * 3 + i) * (1 - k)
        braking = start <= ctx.t < start + 1.3
        st.paste_car(img, (lane_x, y), ctx.pal.primary if i == 0 else ctx.pal.speed_color(30 - 25 * k * min(1, strength / 2.5)),
                     110, 52, 90, brake=braking, highlight=i == 0)
        # brake-strength bar
        bx = lane_x + 140
        d.rounded_rectangle([bx, y - 22, bx + 440, y + 22], radius=22, fill=st.mix(ctx.pal.surface, (0, 0, 0), 0.1))
        w = 440 * min(1.0, strength / (1.0 + 0.45 * (n - 1))) * st.ease_out_cubic(k)
        if w > 44:
            d.rounded_rectangle([bx, y - 22, bx + w, y + 22], radius=22,
                                fill=st.mix(ctx.pal.accent, ctx.pal.danger, i / max(1, n - 1)))
        if i > 0 and ctx.t > start - delay + 0.2:
            st.text_center(img, (lane_x - 165, y - 70), "+ delay", st.font("Inter-Bold", 36), ctx.pal.muted,
                           alpha=st.clamp01((ctx.t - (start - delay + 0.2)) / 0.3))
    st.text_center(img, (lane_x + 360, 470), "BRAKING", st.font("Inter-ExtraBold", 36), ctx.pal.muted)
    headline(img, ctx, y=330)
    tag(img, ctx, "ILLUSTRATION")
    return img


# ============================================================== space-time diagram
PLOT = (150, 520, 1000, 1130)  # x0, y0, x1, y1 (pixels)


@functools.lru_cache(maxsize=2)
def _spacetime_image(w: int, h: int, t_max: float, pal_key: tuple) -> Image.Image:
    pal = st.Palette(dict(zip(("danger", "accent", "success"), pal_key)))
    sim = tr.simulate("jam", 300.0)
    img = Image.new("RGBA", (w * 2, h * 2), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    step = 3
    idx = np.arange(0, len(sim.t), step)
    for car in range(tr.N_CARS):
        prev = None
        for i in idx:
            t = sim.t[i]
            if t > t_max:
                break
            x = t / t_max * w * 2
            y = (1 - sim.x[i, car] / tr.RING_M) * h * 2
            col = pal.speed_color(sim.v[i, car] * 3.6)
            if prev and abs(prev[1] - y) < h:  # skip wrap-around segments
                d.line([prev[:2], (x, y)], fill=col + (255,), width=5)
            prev = (x, y)
    return img.resize((w, h), Image.LANCZOS)


@template("spacetime_diagram", "Time-position plot of every simulated car; jam stripes slope backwards. "
                               "params: t_max, highlight_text")
def spacetime_diagram(ctx: FrameCtx) -> Image.Image:
    img = background(ctx.pal)
    d = ImageDraw.Draw(img)
    x0, y0, x1, y1 = PLOT
    t_max = float(ctx.params.get("t_max", 300.0))
    st.rounded_panel(img, (x0 - 40, y0 - 40, x1 + 40, y1 + 40), radius=30, fill=st.mix(ctx.pal.surface, (0, 0, 0), 0.25))
    pal_key = tuple(f"#{c[0]:02x}{c[1]:02x}{c[2]:02x}" for c in (ctx.pal.danger, ctx.pal.accent, ctx.pal.success))
    full = _spacetime_image(x1 - x0, y1 - y0, t_max, pal_key)
    reveal = st.ease_in_out(ctx.t / max(1.0, ctx.dur * 0.55))
    cut = int((x1 - x0) * reveal)
    if cut > 0:
        part = full.crop((0, 0, cut, y1 - y0))
        img.paste(part, (x0, y0), part)
    d.line([(x0, y1), (x1, y1)], fill=ctx.pal.muted, width=4)
    d.line([(x0, y0), (x0, y1)], fill=ctx.pal.muted, width=4)
    st.arrow(d, (x0 - 60, y1 - 20), (x0 - 60, y0 + 40), ctx.pal.success, width=10, head=28)
    lf = st.font("Inter-Bold", 34)
    st.text_center(img, ((x0 + x1) / 2, y1 + 70), "TIME →", lf, ctx.pal.muted)
    rot = Image.new("RGBA", (420, 60), (0, 0, 0, 0))
    ImageDraw.Draw(rot).text((210, 30), "POSITION ON TRACK", font=lf, fill=ctx.pal.muted + (255,), anchor="mm")
    rot = rot.rotate(90, expand=True)
    img.paste(rot, (x0 - 130, int((y0 + y1) / 2 - 210)), rot)
    if ctx.t > ctx.dur * 0.6:
        k = st.ease_out_cubic((ctx.t - ctx.dur * 0.6) / 0.6)
        # follow the slowest region: jam band slope from the simulation (drawn as a guide arrow)
        sim = tr.simulate("jam", 300.0)
        drift = tr.jam_drift_kmh(sim) / 3.6  # m/s (negative = backwards)
        span = 60.0
        dy_full = -(drift * span) / tr.RING_M * (y1 - y0)
        tA = 160.0
        for cand in np.arange(160.0, 235.0, 2.0):
            pos = _jam_position(sim, cand)
            if (1 - pos / tr.RING_M) * (y1 - y0) + dy_full < (y1 - y0) * 0.92:
                tA = float(cand)
                break
        posA = _jam_position(sim, tA)
        pA = (x0 + tA / t_max * (x1 - x0), y0 + (1 - posA / tr.RING_M) * (y1 - y0))
        pB = (x0 + (tA + span) / t_max * (x1 - x0), pA[1] + dy_full)
        pB = (pA[0] + (pB[0] - pA[0]) * k, pA[1] + (pB[1] - pA[1]) * k)
        st.arrow(d, pA, pB, ctx.pal.text, width=12, head=34)
        st.pill(img, (W / 2, y0 + 70), ctx.params.get("highlight_text", "JAM DRIFTS BACKWARDS"),
                st.font("Inter-ExtraBold", 40), ctx.pal.background, ctx.pal.accent, alpha=k)
    headline(img, ctx, y=330)
    tag(img, ctx, "SIMULATION DATA  ·  RED = STOPPED, GREEN = MOVING")
    return img


@template("video_clip", "Placeholder: AI video clips are composited by the editor, not drawn")
def video_clip(ctx: FrameCtx) -> Image.Image:
    return background(ctx.pal)


def render_frame(name: str, ctx: FrameCtx) -> Image.Image:
    fn = TEMPLATES.get(name)
    if fn is None:
        raise KeyError(f"unknown template {name}")
    img = fn(ctx)
    if img.size != (W, H):
        img = img.resize((W, H))
    return img.convert("RGB")


def describe_templates() -> list[str]:
    return [f"{k}: {v}" for k, v in DESCRIPTIONS.items()]
