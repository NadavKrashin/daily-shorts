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
- **Production is automatic.** The scheduled task `trig_0182qs4pQ7PAjPxr7pJdhums` ("Why in Clay
  episode") runs Mon/Wed/Fri at 08:58 Asia/Jerusalem.
  - It fires into a dedicated production session, `session_019RDtGY8g3sTANrfbpeBBTg` ("Why in Clay:
    episode production", tag `why-in-clay:production`, Auto mode). That session has the repo and the
    Higgsfield connector, which shows up there under a server-ID tool name. Its setup was checked on
    2026-10-16.
  - Each run follows `channel/why-in-clay.md` steps 0-9, including step 6b (overlays).
  - Why a dedicated session: scheduled tasks that start a fresh session can't attach connectors on
    this account, so a fresh session would have no Higgsfield.
  - If the production session is archived, the task stops. To fix it, create a new session from the
    repo with `create_session` (permission_mode auto), confirm Higgsfield `balance` works there, then
    point a new task at it with `create_trigger` and `persistent_session_id`, reusing the prompt
    (`list_triggers`).
- **Credits:** 585.9 on the Higgsfield Plus plan as of 2026-10-16. An episode costs about 150, and runs
  pause by themselves under 200. Buying credits or changing the plan is the owner's call.
- **App: running on the owner's Mac mini** (reported by the owner 2026-10-16; this cloud session can't
  reach the Mac, so those details are as reported, not checked from here).
  - Dashboard: https://atlass-mac-mini-2.tailf9f0e7.ts.net. Reachable only on the owner's tailnet
    (Tailscale Serve; Funnel off). Login is user `ceo`; the password is in
    `~/.why-in-clay-dashboard-password` on the Mac.
  - It runs **natively, not in Docker**:
    - Code: `~/daily-shorts`, on branch **`main`**.
    - Postgres: a Homebrew service that only accepts connections from the Mac itself.
    - Four launchd services start at login and restart if they crash: dashboard (listens on localhost
      only; Tailscale forwards to it), worker, scheduler, and `git pull` every 15 minutes.
    - Logs: `~/daily-shorts/logs/`.
  - A separate `whyinclay` folder on the Mac is an older copy on the other branch; it isn't used.
  - The owner's Cloudflare tunnel and studio.animoment.co.il are separate and must stay untouched.
  - Config: `production_source: claude_runs`. Every 30 minutes the `import_episodes` job turns
    `channel/episodes.json` entries into videos, runs QC, then auto-approves and schedules them.
  - Episode 1 is imported (QC 95.5) and scheduled.
  - `dry_run_mode` is still true, so nothing posts until the owner turns it off in the dashboard.
- **Repo: `NadavKrashin/whyinclay`, one branch: `main`** (owner's choices, 2026-10-16).
  - Everything, including the production runs, commits and pushes straight to `main`, and the Mac
    pulls it every 15 minutes. Never force-push `main`.
  - The repo was renamed from `daily-shorts`; GitHub redirects the old URL. Local checkouts keep the
    folder name `daily-shorts`: `/home/user/daily-shorts` in cloud sessions, `~/daily-shorts` on the
    Mac, whose launchd services use that path.
  - The old `claude/happy-cannon-dzuzwj` branch is deleted, and `main` is the default branch
    (checked 2026-10-16).
  - Still pending: the scheduled task's stored prompt names the old branch. The production session
    (already on `main`) declined to rewrite it on another session's word, which was correct. The owner
    tells it directly to apply the main-only prompt.
- **Episode 2 not made yet.** The 2026-10-16 08:58 run ("Why your brain fills in your blind spot") died
  when the production session's worker restarted. No credits were spent and nothing was committed.
  The next scheduled run (Mon 2026-10-19 08:58) makes it, or the owner can ask the production session
  to run it now.

## What the owner still has to do (details in `docs/setup-guide.md`)

1. Don't archive the "Why in Clay: episode production" session, and keep it on Auto mode. I can't
   change my own permissions: writing `.claude/settings.json` was blocked as self-modification. Don't
   try to work around that.
2. Decide on credits: top up or upgrade, or cut the cadence.
3. Claim "Why in Clay" / @whyinclay on YouTube, Instagram (Professional), Facebook Page and TikTok.
4. ~~Deploy the app~~ Done 2026-10-16 on the Mac mini (see "App" above). Still to confirm: the
   dashboard opens from the owner's phone over Tailscale.
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

## Recent commits (`main`)

- `6e73cb6`: overlays, episode importer, Docker root fix, config-copy fix, setup guide.
- `cc49ae9`: episode 1 v4 (red dots removed).
- `fd7c68c`: narration fixes + `check_takes.py`.
- `0aadee6`: rebrand to Why in Clay, autonomous mode, recipe, yt skill pack.
