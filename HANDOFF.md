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
    - Three launchd services start at login and restart if they crash: dashboard (listens on localhost
      only; Tailscale forwards to it), worker and scheduler.
    - Code updates deploy themselves: every 15 minutes `scripts/mac-mini-update.sh` pulls `main` and,
      if anything besides episodes or docs changed, migrates and restarts the services. A push to
      `main` is live on the Mac within about 15 minutes. Details: `docs/deploy-mac-mini.md`.
    - Logs: `~/daily-shorts/logs/`.
  - A separate `whyinclay` folder on the Mac is an older copy on the other branch; it isn't used.
  - The owner's Cloudflare tunnel and studio.animoment.co.il are separate and must stay untouched.
  - Config: `production_source: claude_runs`. Every 30 minutes the `import_episodes` job turns
    `channel/episodes.json` entries into videos, runs QC, then auto-approves and schedules them.
  - Episode 1 is imported (QC 95.5) and scheduled.
  - `dry_run_mode` is **off** (owner, 2026-10-16 afternoon): posts are real. Episode 1 was scheduled
    while dry-run was on; `publish()` now re-files such jobs under the current mode, so its posts are
    recorded as real ones.
- **Repo: `NadavKrashin/whyinclay`, one branch: `main`** (owner's choices, 2026-10-16).
  - Everything, including the production runs, commits and pushes straight to `main`, and the Mac
    pulls it every 15 minutes. Never force-push `main`.
  - The repo was renamed from `daily-shorts`; GitHub redirects the old URL. Local checkouts keep the
    folder name `daily-shorts`: `/home/user/daily-shorts` in cloud sessions, `~/daily-shorts` on the
    Mac, whose launchd services use that path.
  - The old `claude/happy-cannon-dzuzwj` branch is deleted, and `main` is the default branch
    (checked 2026-10-16).
  - The scheduled task's stored prompt now says main-only (the owner had the production session apply
    it; checked 2026-10-16).
- **Episode 2 ("Why your brain fills in your blind spot") is not on `main` yet.** The 2026-10-16 08:58
  run died when the production session's worker restarted (no credits spent). The owner then asked the
  production session to run it again; check `channel/episodes.json` on `main` for whether it landed.
  When it does, the Mac imports it within about 45 minutes (15-minute pull + 30-minute import).

## What the owner still has to do (details in `docs/setup-guide.md`)

1. Don't archive the "Why in Clay: episode production" session, and keep it on Auto mode. I can't
   change my own permissions: writing `.claude/settings.json` was blocked as self-modification. Don't
   try to work around that.
2. Decide on credits: top up or upgrade, or cut the cadence.
3. ~~Claim the accounts~~ Done 2026-10-16: YouTube, Instagram (Professional, Education) and TikTok.
   There is no Facebook Page, so Facebook publishing is off.
4. ~~Deploy the app~~ Done 2026-10-16 on the Mac mini (see "App" above). Still to confirm: the
   dashboard opens from the owner's phone over Tailscale.
5. Platform credentials: YouTube and Instagram connected 2026-10-16 (see "Platform accounts").
   Still open:
   - restart the services and confirm Settings shows youtube ✓ and instagram ✓
   - get Google **Publish app** to work, then rerun `scripts/youtube_auth.py` (until then the token
     lapses every 7 days)
   - ~~apply for the YouTube API audit~~ Submitted 2026-10-16; waiting for Google (uploads stay
     private until it is approved)
   - TikTok stays a manual handoff
   No R2 bucket is needed.
6. ~~Turn off `dry_run_mode`~~ Done 2026-10-16 (as reported by the owner).

When the owner reports one of these done, help verify it: run the health check and look at the
dashboard Agents page. Never claim it is live without checking.

## Platform accounts (2026-10-16)

- TikTok: the owner posts by hand from the dashboard's download package (owner's choice,
  2026-10-16). Automatic posting via Upload-Post (Basic plan, $24/mo then) is the chosen future option
  once the channel earns money. The comparison and switch steps are in `docs/setup-guide.md` → TikTok.
  Don't build the adapter until the owner asks.
- The owner created the YouTube, TikTok and Instagram accounts for Why in Clay. There is no Facebook
  Page, so `platforms.facebook.enabled: false`.
- Connecting them is the owner's part (`docs/setup-guide.md` step 6). YouTube uses
  `scripts/youtube_auth.py`.
- Instagram: connected 2026-10-16 through a Meta app with no business portfolio ("Why In Clay-IG"),
  with @whyinclay as an Instagram Tester. The 60-day token is renewed every Monday by the
  `instagram_token_refresh` job (`waitwhy/publishing/tokens.py`). The renewed token lives in
  `data/state/instagram_token.json` (mode 600), never in the database, because the Settings page shows
  every DB setting. Its expiry date is in the `instagram_token_status` setting.
- Instagram fetches each video from a public URL. For imported episodes that is the Higgsfield CDN
  link in the version manifest (`source_url`): the same bytes that passed QC. See
  `publishing.service.public_video_url`. No R2 bucket is needed.
- YouTube: connected 2026-10-16 with `scripts/youtube_auth.py` (channel "Why In Clay", a brand
  account). The Google app was still in "Testing", so the refresh token lapses after 7 days until the
  owner gets **Publish app** to work and reruns the script. Uploads stay private until Google's API
  audit is approved.

## YouTube API audit (submitted 2026-10-16)

- The owner submitted Google's YouTube API Services compliance audit form on 2026-10-16. The first
  attempt hung while loading; the second (new tab, small files, optional uploads skipped) showed
  "Your email has been sent. Thank you for submitting the YouTube API Services Form."
- Waiting for Google's reply (it and any follow-up questions go to whyinclay@gmail.com). Reviews
  usually take days to weeks. Until it is approved, uploads from the project are forced to private and
  the dashboard gives a "make public in YouTube Studio" task for each video.
- The form answers are in a Google Doc in krashin23's Drive ("Audit form answers").
- Materials:
  - privacy policy and terms of service: Google Docs in krashin23's Drive, published to the web; the
    privacy policy is also in `docs/privacy-policy.md`
  - diagrams: `docs/audit/`
- What the form declared, which the app must stay within:
  - client "Why in Clay Publisher": internal, single user, only the Why In Clay channel
  - endpoints: `videos.insert` (at most 1 a day), `videos.list`, `channels.list`, Analytics `reports.query`
  - default 10,000 units/day quota; no `search.list`
- Any change to that use (other channels, new endpoints, other users) must be reported to YouTube
  and approved first.
- Promised in the privacy policy: if the owner revokes access, stored YouTube statistics are deleted
  within 30 days. This is a manual step today.
- When Google replies, draft answers for the owner from this section. Never invent capabilities or
  numbers.

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
- **Times:** the Mac's Postgres runs on Israel time; `db.get_engine` forces UTC sessions so labels
  saying UTC are true. The Calendar shows owner time (`timezone` in config) and UTC side by side.
- **Docker image:** it installs the package into site-packages, so it relies on `WAITWHY_ROOT=/app`.
  The compose file mounts `./channel` read-only.

## Recent commits (`main`)

- `6e73cb6`: overlays, episode importer, Docker root fix, config-copy fix, setup guide.
- `cc49ae9`: episode 1 v4 (red dots removed).
- `fd7c68c`: narration fixes + `check_takes.py`.
- `0aadee6`: rebrand to Why in Clay, autonomous mode, recipe, yt skill pack.
