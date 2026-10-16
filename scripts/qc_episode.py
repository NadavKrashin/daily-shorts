"""Run the Mac's import check on an episode before pushing it, so it can't be held after the push.

The app on the Mac imports each episode from channel/episodes.json and runs this exact check
(``waitwhy.importer.evaluate``): the 14 technical checks, the run's recorded checks, sources and
rights. A failed check means the episode is held and never posted. Production runs this first:

    python3 scripts/qc_episode.py 3                       # episode 3, downloads its video_url
    python3 scripts/qc_episode.py 3 --file final_v.mp4    # a local render, before uploading it
    python3 scripts/qc_episode.py --all                   # every episode waiting to be imported

Exit code 0 means it would pass on the Mac (and auto-post if the score is 90 or more), 1 means held.
Needs the package's dependencies (`pip install -e .`) and ffmpeg/ffprobe.
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from waitwhy import importer  # noqa: E402
from waitwhy.settings import load_company_config  # noqa: E402

AUTO_POST_SCORE = 90


def check(cfg: dict, ep: dict, file: Path | None = None) -> bool:
    with tempfile.TemporaryDirectory(prefix="qc-") as d:
        path = file or importer.download(ep["video_url"], Path(d) / "video.mp4")
        r = importer.evaluate(cfg, ep, Path(path))
    print(f"Episode {ep.get('number')}: {ep.get('title')}")
    for c in r["checks"]:
        mark = "PASS" if c["passed"] else ("FAIL" if c["mandatory"] else "note")
        print(f"  {mark:4} {c['name']}: {c['detail']}")
    if not r["passed"]:
        print(f"  => HELD on the Mac: {len(r['blocking'])} blocking issue(s). Fix before pushing.")
    elif r["score"] < AUTO_POST_SCORE:
        print(f"  => passes, but score {r['score']} < {AUTO_POST_SCORE}: waits for the owner's approval.")
    else:
        print(f"  => would be approved and posted automatically (score {r['score']}).")
    return r["passed"] and r["score"] >= AUTO_POST_SCORE


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("number", nargs="?", type=int, help="episode number in channel/episodes.json")
    ap.add_argument("--file", type=Path, help="check this local video instead of the episode's video_url")
    ap.add_argument("--all", action="store_true", help="every episode the Mac would import")
    a = ap.parse_args(argv)
    cfg = load_company_config()
    eps = json.loads(importer.episodes_path(cfg).read_text())["episodes"]
    if a.all:
        todo = [e for e in eps if e.get("status") in importer.IMPORTABLE and e.get("video_url")]
    else:
        if a.number is None:
            ap.error("give an episode number or --all")
        todo = [e for e in eps if e.get("number") == a.number]
        if not todo:
            ap.error(f"episode {a.number} is not in channel/episodes.json")
    ok = [check(cfg, e, a.file) for e in todo]
    return 0 if all(ok) else 1


if __name__ == "__main__":
    sys.exit(main())
