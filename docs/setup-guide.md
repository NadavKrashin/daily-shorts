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
- Don't archive the production session (the one titled "Why in Clay: episode production", created
  2026-10-16 18:40 UTC). The scheduled task "Why in Clay episode" fires into it. The older session
  titled "old production session (retired)" can be archived.
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

## 5. Storage that platforms can pull from (not needed now)

Instagram and Facebook fetch the video from a public URL. Episodes made by the production runs
already have one: the Higgsfield CDN copy that the app downloaded and checked. The publisher uses that
link when storage has none, so nothing needs setting up here.

You only need a bucket if you want the app to serve its own copies, for example videos rendered by the
built-in renderer. Then create a Cloudflare R2 bucket (or S3/B2) with a public URL, set `S3_BUCKET`,
`S3_ENDPOINT_URL`, `S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY` and `S3_PUBLIC_BASE_URL`, and set
`providers.storage: s3`.

## 6. Connect the platforms (one at a time, YouTube first)

The keys go into `~/daily-shorts/.env` on the Mac. Restart the app's services after changing it.
Nothing posts until you turn dry-run off (step 8), so connecting a platform is safe.

### YouTube (about 15 minutes)
1. Open https://console.cloud.google.com, signed in as the Google account that owns the Why in Clay
   channel. Create a project called "Why in Clay".
2. APIs & Services → Library: enable **YouTube Data API v3** and **YouTube Analytics API**.
3. APIs & Services → OAuth consent screen: choose External, app name "Why in Clay", and your email.
   Then, under Audience, click **Publish app** so the status reads "In production". In "Testing", Google
   expires the sign-in after 7 days and uploads would stop. Google calls it "unverified"; that is
   fine for your own channel.
4. APIs & Services → Credentials → Create credentials → OAuth client ID → type **Desktop app** →
   Download JSON.
5. On the Mac: `cd ~/daily-shorts && python3 scripts/youtube_auth.py ~/Downloads/client_secret_*.json`
   - Sign in, pick the **Why in Clay** channel, and tick every permission. The "Google hasn't verified
     this app" page is your own app: click Advanced → Go to Why in Clay.
   - The script prints the channel name it connected to and saves the three YouTube keys to `.env`.
6. **Apply for the YouTube API audit** (YouTube API Services audit and quota extension form). Until
   Google approves it, uploads from a new API project are forced to **private**. The app detects this
   and gives you a "make public in YouTube Studio" task for each video.

### Instagram (about 20 minutes)
The app uses Instagram's own login, so no Facebook Page is needed.
1. In the Instagram app: Settings → Account type and tools → **Switch to professional account** →
   Creator → category Education.
2. Open https://developers.facebook.com → My Apps → Create app → type **Business**. Name it
   "Why in Clay".
3. Add the **Instagram** product → "API setup with Instagram login".
4. Under "Generate access tokens", add the @whyinclay account and approve.
5. Copy the account's **user ID** and the **access token** it shows into `.env` as
   `INSTAGRAM_USER_ID` and `INSTAGRAM_ACCESS_TOKEN`.
   - Your own account works while the app stays in development mode; no App Review is needed.
   - The token lasts about 60 days. The app renews it every Monday and keeps the renewed copy in
     `data/state/instagram_token.json` (private, never committed), so `.env` never needs editing again.
     If a renewal fails, you get an alert while there is still time to make a new token.

### Facebook (off for now)
`platforms.facebook.enabled` is `false` because there is no Facebook Page. To add it later:
1. Create a Page and link it to the Instagram account.
2. Add Facebook Login for Business to the same Meta app, with `pages_manage_posts`,
   `pages_read_engagement` and `pages_show_list`.
3. Set `META_PAGE_ID` and `META_PAGE_ACCESS_TOKEN`, then set `enabled: true`.

### TikTok
The default is a **manual handoff**. For each video, the dashboard's Calendar offers a "Download post
package" (video, cover, caption) and a "Mark as posted" box. TikTok only allows automatic posting
for apps that pass its Content Posting API audit (developers.tiktok.com). Once it's approved, set the
`TIKTOK_*` values and `TIKTOK_APP_AUDITED=true`.

**Later option, once the channel earns money: Upload-Post** (the owner's decision 2026-10-16: post
by hand for now). Compared on 2026-10-16:

| Service | Automatic TikTok posting | Price then |
|---|---|---|
| Upload-Post | yes, Basic plan and up | Basic $24/mo, or $16/mo billed yearly |
| Ayrshare | yes | from $149/mo |
| Metricool | API only on the Advanced plan | price unconfirmed |
| Buffer | no new API apps | n/a |

Upload-Post's API covers what we need: `privacy_level=PUBLIC_TO_EVERYONE`, `post_mode=DIRECT_POST`
(or `MEDIA_UPLOAD` for drafts), and `is_aigc=true` for TikTok's AI-generated label. It caps posts at
15 a day per account. Sources: docs.upload-post.com/resources/pricing-and-limits and
docs.upload-post.com/api/upload-video.

To switch:
1. The owner subscribes, connects @whyinclay, and puts the API key in `.env`.
2. A session adds an Upload-Post TikTok adapter, keeping the manual package as the fallback.
3. Check that the first post appears publicly.

## 7. Alerts on your phone (free, 3 minutes)

The app sends a Telegram message whenever something needs you: a TikTok post to make, a failed upload,
an expiring token. Each TikTok message links to the dashboard's Calendar page.
1. In Telegram, open **@BotFather**, send `/newbot`, and give it a name such as "Why in Clay alerts".
2. On the Mac: `cd ~/daily-shorts && git pull && python3 scripts/telegram_setup.py`. Paste the token
   BotFather gave you (it isn't shown), then send your new bot any message in Telegram.
3. The script saves the keys to `.env`, sends a test message and restarts the app.

Email over any SMTP works too (`SMTP_*`, `NOTIFY_EMAIL_TO`, and add `email` to `notifications.channels`).

### Posting to TikTok each time
At the video's slot you get the Telegram alert. Open the Calendar link, then **Download post package**
(video, cover, caption). Upload at tiktok.com/upload or in the app, paste `caption.txt`, set the cover,
turn on **AI-generated content**, and post. Paste the post's link next to the row and click **Mark as
posted**. Slots are 19:00, 00:00 and 02:30 Israel time, so late ones can wait until the morning.

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
