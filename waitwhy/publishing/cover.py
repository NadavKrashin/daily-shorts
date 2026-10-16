"""Portrait cover images for the manual-upload packages (TikTok, Reels).

The production runs make a landscape YouTube-style thumbnail, often several thousand pixels wide and
tens of megabytes as PNG. TikTok wants a portrait cover and rejects big files, so the package gets a
1080x1920 JPEG: a portrait thumbnail is cropped to fit; a landscape one sits full-width in the middle
of a blurred, darkened copy of itself, so its title text stays readable.
"""
from __future__ import annotations

import io
from pathlib import Path

from PIL import Image, ImageEnhance, ImageFilter, ImageOps

SIZE = (1080, 1920)


def portrait_cover(path: Path, quality: int = 88) -> bytes:
    with Image.open(path) as im:
        im = ImageOps.exif_transpose(im).convert("RGB")
        if im.height >= im.width:
            out = ImageOps.fit(im, SIZE, Image.LANCZOS)
        else:
            bg = ImageOps.fit(im, SIZE, Image.LANCZOS).filter(ImageFilter.GaussianBlur(40))
            out = ImageEnhance.Brightness(bg).enhance(0.6)
            fg = im.resize((SIZE[0], round(im.height * SIZE[0] / im.width)), Image.LANCZOS)
            out.paste(fg, (0, (SIZE[1] - fg.height) // 2))
    buf = io.BytesIO()
    out.save(buf, "JPEG", quality=quality, optimize=True)
    return buf.getvalue()
