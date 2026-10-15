"""Captions: word-timed chunks -> SRT (separate deliverable) and ASS (burned in via libass, with the
active word highlighted). Positioned inside the caption safe zone, away from platform UI overlays."""
from __future__ import annotations

import re


def chunk_words(words: list[dict], max_words: int = 4, max_chars: int = 22) -> list[dict]:
    """Group absolute-timed words [{w,s,e}] into short caption chunks, breaking at punctuation."""
    chunks, cur = [], []
    for w in words:
        cur.append(w)
        text = " ".join(x["w"] for x in cur)
        if len(cur) >= max_words or len(text) >= max_chars or re.search(r"[.!?,;:]$", w["w"]):
            chunks.append(cur)
            cur = []
    if cur:
        chunks.append(cur)
    return [{"words": c, "s": c[0]["s"], "e": c[-1]["e"], "text": " ".join(x["w"] for x in c)} for c in chunks]


def _srt_ts(t: float) -> str:
    ms = int(round(t * 1000))
    h, ms = divmod(ms, 3600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _ass_ts(t: float) -> str:
    cs = int(round(t * 100))
    h, cs = divmod(cs, 360_000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h:d}:{m:02d}:{s:02d}.{cs:02d}"


def to_srt(chunks: list[dict]) -> str:
    out = []
    for i, c in enumerate(chunks, 1):
        out.append(f"{i}\n{_srt_ts(c['s'])} --> {_srt_ts(max(c['e'], c['s'] + 0.3))}\n{c['text']}\n")
    return "\n".join(out)


def _ass_color(rgb: tuple[int, int, int]) -> str:
    r, g, b = rgb
    return f"&H00{b:02X}{g:02X}{r:02X}"


def to_ass(chunks: list[dict], *, width=1080, height=1920, font="Inter", size=66, y_center=1330,
           text_rgb=(248, 250, 252), highlight_rgb=(250, 204, 21), margin_lr=110) -> str:
    """One Dialogue per word interval: the chunk stays on screen and the spoken word turns yellow."""
    margin_v = height - y_center - size // 2
    head = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Cap,{font},{size},{_ass_color(text_rgb)},&H000000FF,&H00101828,&H80000000,-1,0,0,0,100,100,0,0,1,7,3,2,{margin_lr},{margin_lr},{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = []
    hl = _ass_color(highlight_rgb)
    for ci, c in enumerate(chunks):
        end_of_chunk = chunks[ci + 1]["s"] if ci + 1 < len(chunks) else c["e"] + 0.4
        end_of_chunk = min(end_of_chunk, c["e"] + 0.6)
        ws = c["words"]
        for wi, w in enumerate(ws):
            start = c["s"] if wi == 0 else w["s"]
            stop = ws[wi + 1]["s"] if wi + 1 < len(ws) else end_of_chunk
            if stop <= start:
                continue
            parts = []
            for wj, x in enumerate(ws):
                tok = x["w"].upper().replace("{", "(").replace("}", ")")
                parts.append(f"{{\\c{hl}}}{tok}{{\\c{_ass_color(text_rgb)}}}" if wj == wi else tok)
            lines.append(f"Dialogue: 0,{_ass_ts(start)},{_ass_ts(stop)},Cap,,0,0,0,,{' '.join(parts)}")
    return head + "\n".join(lines) + "\n"
