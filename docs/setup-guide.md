# Owner setup guide: what only you can do

Everything else runs by itself:
- Scheduled Claude runs make an episode every Mon/Wed/Fri at 08:58 Israel time with Higgsfield
  (`channel/why-in-clay.md`) and push it to `channel/episodes.json`.
- The app (`waitwhy`) imports each episode every 30 minutes and runs technical QC.
- In autonomous mode the app then approves the episode and schedules it for the next audience slot
  (12:00, 17:00 or 19:30 New York, weekdays). It publishes through the official APIs and collects
  analytics, and a morning report goes out at 09:00.

The steps below need your logins, your money or your signature. Do them in order. Never paste secrets
into chat: put them in `.env` on the server.

## 1. Keep the scheduled runs unblocked (2 minutes)

- Episodes are made in their own Claude Code session, **"Why in Clay: episode production"**. Your
  normal chats are separate, so you can archive them freely.
- Don't archive the production session. The scheduled task "Why in Clay episode" fires into it.
- Keep its permission mode on **Auto**, as it is now. A tool-approval prompt with nobody there stalls
  the run.

## 2. Higgsfield credits (your money)

- Your account is on the **Plus** plan with 585.9 credits (checked 2026-10-16).
- An episode costs about 150 credits. The text and diagram overlays add nothing; they are drawn in code.
- At three episodes a week that is about 1,950 credits a month. Runs stop by themselves when the balance
  drops under 200, so with no top-up the schedule pauses after about three more episodes.
- Choose one: top up or upgrade in Higgsfield (Settings → Plans), or tell Claude to cut the schedule to
  the cadence your plan's monthly credits cover.
- Commercial use is fine: Higgsfield's help center says you own your outputs and the Terms (section 4.4)
  don't restrict commercial use on any plan. This is recorded in `config/company.yaml` →
  `episodes.higgsfield_commercial_use_confirmed`. Set it to `false` if the terms ever change; that
  blocks publishing.

## 3. Claim the channel names (15 minutes)

Create these, all named **Why in Clay**, handle `@whyinclay` where it's free:
- a YouTube channel
- an Instagram **Professional** (Creator) account
- a Facebook Page, linked to the Instagram account
- a TikTok account

## 4. A machine for the app

**Your Mac mini (planned):** follow `docs/deploy-mac-mini.md`, about 30 minutes. It covers keeping the
Mac awake, Docker Desktop, a deploy key, auto-pulling new episodes, and Tailscale for phone access.

**Or a cloud VM (your money).** Any Linux VM with 4 vCPU / 8 GB RAM / 80 GB disk works, for example
Hetzner, DigitalOcean or AWS Lightsail. Check the provider's current price. Then follow
`docs/deployment.md`:

```bash
git clone -b main git@github.com:NadavKrashin/whyinclay.git daily-shorts && cd daily-shorts
cp .env.example .env && chmod 600 .env   # APP_ENV=production, DASHBOARD_PASSWORD, SECRET_KEY, POSTGRES_PASSWORD
docker compose up -d --build
( crontab -l; echo '*/15 * * * * git -C ~/daily-shorts pull --ff-only -q' ) | crontab -
```

The repository is private, so add a read-only **deploy key** for the server (GitHub → repo → Settings
→ Deploy keys). The cron line is how new episodes reach the app. A domain with HTTPS (Caddy, see
deployment.md) is optional but recommended for the dashboard.

## 5. Storage that platforms can pull from (free tier is enough to start)

Instagram and Facebook fetch the video from a public URL. Do this:
1. Create a Cloudflare R2 bucket (or S3/B2) with a public access URL.
2. Set `S3_BUCKET`, `S3_ENDPOINT_URL`, `S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY` and `S3_PUBLIC_BASE_URL`.
3. Set `providers.storage: s3` in `config/company.yaml`.

## 6. Connect the platforms (one at a time, YouTube first)

### YouTube
1. Google Cloud Console → new project → enable **YouTube Data API v3** and **YouTube Analytics API**.
2. OAuth consent screen (External, add yourself as a test user) → OAuth client of type "Desktop app".
3. Get a refresh token for the channel's Google account with scopes `youtube.upload`,
   `youtube.readonly` and `yt-analytics.readonly`. Google's OAuth Playground with your own client works.
4. Put `YOUTUBE_CLIENT_ID`, `YOUTUBE_CLIENT_SECRET` and `YOUTUBE_REFRESH_TOKEN` in `.env`.
5. **Apply for the YouTube API audit** (YouTube API Services audit form). Until Google approves it,
   uploads from a new API project are forced to **private**. The app detects this and leaves you a
   "make public in YouTube Studio" task for each video.

### Instagram + Facebook
1. developers.facebook.com → create a Business app → add the Instagram API and Facebook Login for Business.
2. Request `instagram_business_basic`, `instagram_business_content_publish`,
   `instagram_business_manage_insights`, `pages_manage_posts`, `pages_read_engagement` and
   `pages_show_list`. Your own accounts work in development mode as app roles. Other people's need App Review.
3. Generate long-lived tokens and set `INSTAGRAM_USER_ID`, `INSTAGRAM_ACCESS_TOKEN`, `META_PAGE_ID` and
   `META_PAGE_ACCESS_TOKEN`.

### TikTok
The default is a **manual handoff**: the dashboard's Calendar offers a "Download post package" (video,
cover, caption) and a "Mark as posted" box. To automate it, apply for TikTok's Content Posting API
audit (developers.tiktok.com). Once it's approved, set the `TIKTOK_*` values and `TIKTOK_APP_AUDITED=true`.

## 7. Notifications (optional, free)

Create a Telegram bot with @BotFather and set `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`. Then add
`telegram` to `notifications.channels`. Email over any SMTP works too (`SMTP_*`, `NOTIFY_EMAIL_TO`).

## 8. Go live

Dashboard → Settings → set `dry_run_mode` to `false` and confirm with `I AUTHORIZE dry_run_mode`.
Until you do this, publishing uses mock adapters and nothing is posted. After it, every imported
episode that passes QC is approved and scheduled automatically.

## Not needed any more

`production_source: claude_runs` makes Claude runs produce the videos, so these are only for the old
built-in renderer and you can skip them:
- `ANTHROPIC_API_KEY` (reports and analytics work without it; only the optional AI-written strategy summary is skipped)
- `ELEVENLABS_*`
- the Higgsfield **API** keys (a separate wallet from your Higgsfield web plan)

## Still your call, any time

Sponsorship deals and outreach emails, any new paid service, and switching back to supervised mode
(`operating_mode: supervised`) if you want to approve each video before it goes out.
