"""Strict narration check: fail any take whose speech contains words that are not in the script.

Usage (inside the Higgsfield sandbox, which has faster-whisper):
    python3 check_takes.py script_manifest.json VOICE_DIR [--model medium]

Episode 1 shipped three takes where the TTS spoke part of its delivery instruction aloud
("Matter 2008...", "Supposed to you, here's the surprise"). The workflow's similarity check passed
them because most words matched. This check compares letters, not a similarity score: any extra or
replaced stretch of 4+ letters in what was heard fails the take. Digits are spelled out first so
"2008" matches "two thousand eight". Exits 1 if any take fails.
"""
import argparse
import difflib
import json
import re
import sys

ONES = "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen " \
       "sixteen seventeen eighteen nineteen".split()
TENS = "_ _ twenty thirty forty fifty sixty seventy eighty ninety".split()
UNITS = {"km": "kilometres", "kilometers": "kilometres", "kilometer": "kilometre", "%": " percent",
         "meters": "metres", "meter": "metre", "mph": "miles per hour"}


def words(n: int) -> str:
    if n < 20:
        return ONES[n]
    if n < 100:
        return TENS[n // 10] + ("" if n % 10 == 0 else ONES[n % 10])
    if n < 1000:
        return ONES[n // 100] + "hundred" + ("" if n % 100 == 0 else "and" + words(n % 100))
    if n < 10000:
        rest = n % 1000
        return ONES[n // 1000] + "thousand" + ("" if rest == 0 else ("and" if rest < 100 else "") + words(rest))
    return str(n)


def letters(text: str) -> str:
    text = text.lower().replace(",", "")
    for k, v in UNITS.items():
        text = re.sub(rf"\b{re.escape(k)}\b" if k.isalpha() else re.escape(k), v, text)
    text = re.sub(r"\d+", lambda m: words(int(m.group())), text)
    text = text.replace("and", "")  # "two thousand and eight" vs "two thousand eight"
    return re.sub(r"[^a-z]", "", text)


def extras(script: str, heard: str, min_len: int = 4) -> list[str]:
    a, b = letters(script), letters(heard)
    out = []
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if op in ("insert", "replace") and (j2 - j1) >= min_len:
            out.append(f"{op}: heard '{b[j1:j2]}' where script has '{a[i1:i2]}'")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("manifest")
    ap.add_argument("voice_dir")
    ap.add_argument("--model", default="medium")
    args = ap.parse_args()
    from faster_whisper import WhisperModel
    model = WhisperModel(args.model, compute_type="int8")
    blocks = json.load(open(args.manifest))["blocks"]
    failed = []
    for b in blocks:
        n = b["n"]
        segs, _ = model.transcribe(f"{args.voice_dir}/voice{n:02d}.wav", language="en")
        heard = " ".join(s.text.strip() for s in segs)
        problems = extras(b["vo_line"], heard)
        print(json.dumps({"block": n, "ok": not problems, "heard": heard, "problems": problems}), flush=True)
        if problems:
            failed.append(n)
    print(json.dumps({"failed_blocks": failed}))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
