# Why in Clay: production recipe

The channel's locked look, voice and format, and the exact steps a scheduled run follows to make
one episode with no human in the loop. Episode 1 (`channel/episodes/001-traffic-jams/`) is the
worked example: copy its file shapes.

## Channel DNA (locked; change only when the owner asks)

| | |
|---|---|
| Name | Why in Clay (handle `@whyinclay`) |
| Promise | One everyday mystery, explained in 60 seconds of handmade clay |
| Format | 9:16, 60 s = 6 scenes x 10 s, five hard-cut shots per scene (cuts at 2/4/6/8 s) |
| Look | Higgsfield explainer preset **Claymotion** (`1de0f39e-c602-4b00-b54a-38440c7f63f7`). Style key image job `313e8a54-0203-4435-9f21-af07936fc570`. Style formula: `channel/style.txt`, pasted verbatim into every image and video prompt |
| Motion token | `smooth simple handcrafted motion, subtle stop-motion feel` (dimensional style: no "3D render" in negatives) |
| Palette | sky blue, grass green, warm sand, cream; ONE signal-red accent reserved for the episode's through-line prop and warning marks |
| Narrator | **Kevin**, `voice_id f1373f24-3b96-433f-9a68-e595810ef608`, `voice_type preset`, model `text2speech_v2` variant `elevenlabs` |
| Prompt format (every line) | `[excited] {line}`: one plain tag, nothing else. Descriptive brackets and per-line moods get SPOKEN by this voice (episode 1: "Matter 2008", "Supposed to you, here's the surprise") |
| Captions | bottom centre, sentence case, max 4 words a cue: `subtitle_paper_burn.py --style bold --no-caps --font-key montserrat --stroke-frac 0.045 --profile faceless` |
| Thumbnail | 16:9, `nano_banana_pro` 4k, clay medium, people-free, hook text 3-4 words baked in and checked letter for letter |

## Writing rules

- **Kevin talks fast.** Write 21-23 words per scene line and prefer longer words ("accelerating",
  "instructed", "noticeably") over short ones. Short-word lines read above the 2.9 words/second
  limit and fail. Numbers are written as words.
- **Hook (scene 1):** write five candidate first lines, score them with
  `python3 .claude/skills/yt-script/hookscore.py hooks.txt`, and use the best. Aim for a verdict
  above WEAK. The hook confirms the title and opens a question the viewer cannot close.
- **Through-line:** one signal-red element that changes state in every scene and resolves in the
  payoff. It must be something the viewer already understands (brake lights, a warning sign, a
  thermometer) or something the narration names. Abstract symbols the voice never explains read as
  random (episode 1's lone red clay dot at 0:17 confused the owner).
  The script validator requires `through_line.asset` in every block's `assets_used`, so make it a
  prop that is naturally in every scene (episode 1's final through-line is the brake lights on the
  sand car).
- **Direction of travel:** for anything that moves, state which way it faces and moves in the shot
  text, and put the reverse motion in the negatives (episode 1 had a car reversing at 0:37).
- **Arc:** hook (1), build (2-4), turn (5), payoff (6). The payoff answers the hook.
- **Facts:** every claim traces to a primary or reputable source found this run. Put the URLs in
  the manifest's `sources`. Prefer "roughly" over a false-precise number. Never invent a figure,
  study or quote. Skip topics with any `risk_flags`.
- **Title and thumbnail:** run `python3 .claude/skills/yt-package/title.py --title "..." --thumb "..."`
  and fix every `x` it reports when you can. The thumbnail must not repeat the title's words.
- Use the yt-* skills' rules and tools, but skip their closing "ship it, or change it?" question.
  Scheduled runs never stop to ask.

## Run steps

Each step names the Higgsfield workflow script to use. Load `get_workflow_instructions` for
`faceless-video`, `narration`, `video-montage` and `thumbnail-generation` at the start of a run and
follow them, except where this file says otherwise.

0. **Credit guard.** Call `balance`. If below 200 credits, stop: make nothing and report
   "paused: N credits left". One episode costs about 150 credits. Never buy credits or change the plan.
1. **Topic.** Take the highest-scoring topic in `seeds/topics.json` whose slug is not in
   `channel/episodes.json` and has no `risk_flags`.
2. **Research + script.** Search the web, fact-check, and write `channel/episodes/NNN-slug/script_manifest.json`
   in episode 1's shape: blocks with `vo_line`, five `shots` (vary size and angle on every cut, no
   OTS, no people), `assets_used` (max 7: location first), `through_line_state` and `audio`
   (2-4 diegetic clay SFX cues). Validate with
   `validate_motion_script.py --script script_manifest.json --duration-seconds 60` until `valid: true`.
3. **Narration first** (cheap; it proves the script fits before the 120-credit video spend). One
   `generate_audio_batch` with all six lines in the format
   `[excited] {line}` (this overrides the narration workflow's timecode format, which leaked words).
   Convert with the narration workflow's reverse-trim recipe, measure with
   `measure_narration_takes.py`, then run `python3 check_takes.py script_manifest.json work/voices`
   (upload `channel/tools/check_takes.py` to the sandbox). It fails any take containing words that are
   not in the script. The workflow's own `verify_takes.py` is NOT enough: it passed all three bad
   takes in episode 1. The captions show script words, so they hide spoken mistakes. Regenerate only
   failing lines (max 3 attempts per line; the third needs new words).
4. **Assets.** `generate_image_batch`, `seedream_v5_pro`, `1k`, style key `313e8a54-...` as
   `image_references`. Locations 9:16, empty sets, dark clay asphalt where there is a road. Props 1:1
   on a plain pale sky-blue background. Look at every image before using it and regenerate any set
   that clashes with the props (episode 1's first highway came out sand-coloured and hid the sand cars).
   Write `assets.json` (`{name: {id, desc}}`).
5. **Scenes.** `python3 channel/tools/build_blocks.py channel/episodes/NNN-slug > block_reqs.json`,
   then one `generate_video_batch` with that array. Wait with `jobs_wait`. Check each clip: audio
   stream present, about 4 cuts near 2/4/6/8 s, frames match the sets and props, no people or text.
   Look at a strip of frames every 0.5 s for each shot, not one frame per shot: reversing cars and
   stray objects only show up as motion.
   Regenerate a scene only for a named failure (wrong style, missing audio, person or text on
   screen), at most twice.
6. **Assemble + captions + upload** in ONE background `sandbox_exec`: `media_upload` first, then
   `finish_video.sh --blocks 6 ... --out work/output/final_clean.mp4`, the caption fragment, then the
   PUT. Gotchas from episode 1:
   - The sandbox refuses pasted base64 files. Upload the manifest with `media_upload` and curl it.
   - Presigned PUTs need the header `If-None-Match: *`.
   - The assembler sidecar names voices `v_000.wav`...; symlink `work/voices/voiceNN.wav` to those
     names in a separate folder and pass it as `--voice-dir` with `--per-block`.
   - Lines with numbers align badly (Whisper writes digits). Add `--minimum-similarity 0.70` after
     confirming the take says the right words.
   - `sandbox_exec` foreground calls time out at 60 s; run long work with `background:true` and poll.
   Inspect frames at a few cue midpoints before `media_confirm`.
7. **Thumbnail.** Follow `thumbnail-generation` with the faceless Phase-8b handoff (non-photoreal clay
   medium, people-free, one variant). Verify the baked text. Upload it.
8. **Record.** Append the episode to `channel/episodes.json` (urls, credits spent = balance before
   minus after, sources, known issues). Commit `channel/` and push to the working branch.
9. **Report** in the final message: the video and thumbnail links, title, description draft
   (`yt-seo` rules), the sources, what failed and was fixed, and credits spent and remaining.

## Hard limits (never crossed, never asked about)

- Never publish anywhere from a scheduled run until the publishing app is deployed with platform
  accounts connected. Until then a run ends with links, not posts.
- Never spend more than 200 credits on one episode. If retries would cross that, ship what passes
  and report the gap.
- Never fabricate analytics, facts, sources or test results. If a check could not run, say so.
- Never use a real person's likeness or voice, and never use copyrighted characters or music.
