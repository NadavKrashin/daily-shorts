# Handoff: where to pick up

Read this first in any new session, then `CLAUDE.md` and `channel/why-in-clay.md`. Last updated 2026-10-16.

## State right now

- **Episode 1 is finished:** "Why Traffic Jams Appear Out of Nowhere", v5 (status
  `produced_not_published`, not posted anywhere).
  - Video: https://d2ol7oe51mr4n9.cloudfront.net/user_3GwgNHZqxuXDkDZnfXEEDAP3y0F/e3fa913d-9646-4721-9e23-5613ac164da4.mp4
  - Older cuts and the reasons for each fix are listed in `channel/episodes.json`.
  - All four problems the owner reported are fixed: spoken words at 0:11 and 0:31, a red dot at 0:17
    and a reversing car at 0:37.
  - v5 adds 14 on-screen text and diagram overlays (owner request: "more text and explanatory animations").
- **Production is automatic.** The scheduled task `trig_01NvBXgrzynfnKVDVQZeGxzL` ("Why in Clay
  episode") runs Mon/Wed/Fri at 08:58 Asia/Jerusalem.
  - It fires into session `session_01TgP7K6kDYwbqhy96bKL9fm` and follows `channel/why-in-clay.md`
    steps 0-9, including step 6b (overlays).
  - If that session is archived, the task stops: recreate it with the same prompt (read it with
    `list_triggers`).
- **Credits:** 585.9 on the Higgsfield Plus plan as of 2026-10-16. An episode costs about 150, and runs
  pause by themselves under 200. Buying credits or changing the plan is the owner's call.
- **App:** the `waitwhy` app is built and tested (79 passed, 1 skipped) but **not deployed**.
  - Config: `production_source: claude_runs`.
  - Every 30 minutes the `import_episodes` job turns `channel/episodes.json` entries into videos, runs
    QC, then auto-approves and schedules them.
  - `dry_run_mode` is still true, so nothing posts.

## What the owner still has to do (details in `docs/setup-guide.md`)

1. Keep the permission mode on Auto so scheduled runs don't stall. I can't change my own permissions:
   writing `.claude/settings.json` was blocked as self-modification. Don't try to work around that.
2. Decide on credits: top up or upgrade, or cut the cadence.
3. Claim "Why in Clay" / @whyinclay on YouTube, Instagram (Professional), Facebook Page and TikTok.
4. Rent a server and deploy (`docs/deployment.md`): a read-only deploy key plus a host cron `git pull`.
5. Set up an R2/S3 bucket, then platform credentials:
   - YouTube OAuth, plus the API audit (uploads stay private until Google approves it)
   - Meta app and tokens
   - TikTok: manual handoff by default
6. Turn off `dry_run_mode` in the dashboard to go live.

When the owner reports one of these done, help verify it: run the health check and look at the
dashboard Agents page. Never claim it is live without checking.

## Open quality items (fix in future episodes, not urgent)

- Episode 1's hook scored WEAK (31) on `hookscore.py`, and its thumbnail text is 5 words (limit 3).
- The red strip on the scene-5 chart is never named by the narration.
- The `ring`/`wave` overlay diagrams are traffic-specific. For a new topic, add a diagram type to
  `channel/tools/overlays.py` drawn from a real model or real numbers, or use cards and chains.

## How things work (gotchas learned the hard way)

- **Higgsfield sandbox:**
  - It refuses pasted base64. Move files with `media_upload` + curl PUT (header `If-None-Match: *`)
    + `media_confirm`, then curl the CDN URL.
  - Foreground commands time out at 60 s; use `background: true` and poll.
  - Episode 1's working files are in the sandbox under `~/clay/` (they may expire).
- **Narration:** use the plain `[curious]` tag only. Descriptive tags get spoken aloud.
  - `channel/tools/check_takes.py` is the real check; the workflow's `verify_takes.py` missed bad takes.
- **Overlays:** `python3 overlays.py manifest captions.json in.mp4 out.mp4 --still T` renders previews.
  - Run it without `--still` for the full render, about 2 minutes in the background.
  - Timing comes from the `at`/`until` phrases looked up in `final.words.json`.
- **Tests:** Postgres data lives in `/var/lib/postgresql/wwdata`.
  - Start it: `su postgres -c "/usr/lib/postgresql/*/bin/pg_ctl -D /var/lib/postgresql/wwdata -l /var/lib/postgresql/wwdata/log start"`.
  - Run: `SKIP_SLOW=1 .venv/bin/python -m pytest -q`.
  - Databases: `waitwhy`, `waitwhy_test`, `waitwhy_mig` (scratch). A fresh container may need Postgres
    and the venv reinstalled.
- **Docker image:** it installs the package into site-packages, so it relies on `WAITWHY_ROOT=/app`.
  The compose file mounts `./channel` read-only.

## Recent commits (branch `claude/happy-cannon-dzuzwj`)

- `6e73cb6`: overlays, episode importer, Docker root fix, config-copy fix, setup guide.
- `cc49ae9`: episode 1 v4 (red dots removed).
- `fd7c68c`: narration fixes + `check_takes.py`.
- `0aadee6`: rebrand to Why in Clay, autonomous mode, recipe, yt skill pack.
