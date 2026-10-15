"""Build the six minimax_h3 block requests for a Why in Clay episode.

Usage: python3 channel/tools/build_blocks.py EPISODE_DIR > block_reqs.json

EPISODE_DIR holds script_manifest.json (blocks with shots, assets_used, audio) and assets.json
({asset_name: {"id": generation_job_id, "desc": "LOCATION (...)" | "PROP ..."}}). The style
formula comes from channel/style.txt and is pasted verbatim, so every episode shares one look.
The output is the `requests` array for generate_video_batch.
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
STYLE = open(os.path.join(HERE, "..", "style.txt")).read().strip()
MOTION = "smooth simple handcrafted motion, subtle stop-motion feel"
# Higgsfield sometimes answers a minimax_h3 request with a preset suggestion instead of a job;
# declining it up front avoids a wasted round trip.
DECLINED_PRESET = "24bae836-2c4a-48e0-89b6-49fcc0b21612"
CUTS = [0.0, 2.0, 4.0, 6.0, 8.0, 10.0]


def build(episode_dir: str) -> list[dict]:
    manifest = json.load(open(os.path.join(episode_dir, "script_manifest.json")))
    assets = json.load(open(os.path.join(episode_dir, "assets.json")))
    palette = manifest.get("palette_lock", "painted sky-blue backdrop with cotton-wool clouds, green and "
                           "sandy clay ground, dark clay asphalt; signal red ONLY on warning marks and the "
                           "through-line prop")
    reqs = []
    for b in manifest["blocks"]:
        refs = b["assets_used"]
        if len(refs) > 7:
            raise SystemExit(f"block {b['n']}: {len(refs)} references, the limit is 7")
        missing = [r for r in refs if r not in assets]
        if missing:
            raise SystemExit(f"block {b['n']}: no asset id for {missing}")
        if len(b["shots"]) != 5:
            raise SystemExit(f"block {b['n']}: needs exactly 5 shots")
        refline = " ".join(f"@Image{i + 1} = {assets[r]['desc']}." for i, r in enumerate(refs))
        shots = "\nHARD CUT.\n".join(
            f"SHOT {i + 1} — {CUTS[i]:.1f}s to {CUTS[i + 1]:.1f}s — {s}." for i, s in enumerate(b["shots"]))
        prompt = (
            f"Style: {STYLE}; {MOTION} — the visual style is EXACTLY as in the reference images, same rendering, "
            "same surface treatment.\n"
            f"PALETTE LOCK: use ONLY the colors and the background treatment of the reference images ({palette}). "
            "Do NOT introduce any new or foreign colors, no colored/gradient/painted backgrounds that aren't in the "
            "references, no recoloring of the props.\n"
            "A single 10-second scene of FIVE hard-cut shots. Do NOT open the video on any reference image or show "
            "a sheet/swatch — stage everything fresh, matching props, sets, colors and background to their "
            "references. No people appear: no humans, no hands, no animator's fingers. Motion starts on frame 1 "
            "(no opening freeze).\n"
            f"REFERENCES (look, identity, palette): {refline}\n"
            f"{shots}\n"
            f"Five hard-cut shots at 2.0s, 4.0s, 6.0s and 8.0s, no dissolves, no fades. {MOTION}, continuous motion "
            "within each shot, never freezes.\n"
            f"AUDIO: {b['audio']} — no voice, no narration, no music.\n"
            "NEGATIVE: opening on a reference image, a sheet/swatch or a static first frame, leading freeze, "
            "dissolves or fades, NEW or foreign colors, colored/gradient/painted background not in the references, "
            "recolored props, style drift, people, hands, fingers, on-screen text, captions, letters, numbers, "
            "photorealism, live-action footage, watermark.")
        reqs.append({"index": b["n"], "params": {
            "model": "minimax_h3", "duration": 10, "resolution": "2K", "aspect_ratio": "9:16",
            "prompt": prompt, "declined_preset_id": DECLINED_PRESET,
            "medias": [{"value": assets[r]["id"], "role": "image_references"} for r in refs]}})
    return reqs


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    print(json.dumps(build(sys.argv[1]), ensure_ascii=False))
