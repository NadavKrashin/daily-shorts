# Owner setup guide: what you need to provide

The system runs today in **dry-run mode** with no accounts. To produce **publishable** videos and go live,
provide the items below. Each one unlocks a specific capability. You can do them in any order. Do not paste
secrets into chat; put them in `.env` on the server, or in your secret manager.

## Minimum to produce publishable videos (≈ 30 minutes)

| # | What | Where | Then set |
|---|---|---|---|
| 1 | **Anthropic API key** (research, fact-checking, scripts, storyboards, QC review) | console.anthropic.com → API keys. Add a payment method; set a monthly spend limit (e.g. $60) in the console as a second safety net | `ANTHROPIC_API_KEY` |
| 2 | **ElevenLabs paid plan + API key + voice** | elevenlabs.io → upgrade to a plan with a commercial license (Creator suggested; verify current tiers) → Profile → API key. Choose a library/designed voice you are licensed to use (warm, curious, moderate energy). **Do not clone a real person's voice** without their written permission | `ELEVENLABS_API_KEY`, `ELEVENLABS_VOICE_ID` |
| 3 | Switch off dry run | Dashboard → Settings → key `dry_run_mode`, value `false`, confirm `I AUTHORIZE dry_run_mode` | — |

With 1–3, every new video uses real research and a licensed voice. QC will mark it **publishable**, and
the publication still waits for your approval in supervised mode.

## Optional: AI hero shots (Higgsfield)

1. https://open.higgsfield.ai → create an API key (id + secret, shown once) → top up the **API wallet** (separate from the
   web-app subscription; min $5).
2. Pick a text-to-video model in https://docs.higgsfield.ai/docs/models.md and put its URL path + body fields in
   `config/company.yaml → higgsfield.video_model_path / video_body_defaults` (the placeholder must be replaced).
3. Set `HIGGSFIELD_API_KEY`, `HIGGSFIELD_API_SECRET`. The storyboard agent may then use up to `max_ai_scenes_per_video`
   AI shots, each budget-checked first.

## Publishing (do one platform at a time; YouTube first)

### YouTube
1. Google Cloud Console → new project → enable **YouTube Data API v3** and **YouTube Analytics API**.
2. OAuth consent screen (External, add yourself as test user) → OAuth client "Desktop app".
3. Obtain a refresh token for the channel account with scopes `youtube.upload`, `youtube.readonly`,
   `yt-analytics.readonly` (e.g. Google's OAuth Playground with your own client).
4. Set `YOUTUBE_CLIENT_ID`, `YOUTUBE_CLIENT_SECRET`, `YOUTUBE_REFRESH_TOKEN`.
5. **Important:** until Google audits the API project, uploads are forced **private**. The system detects this and gives
   you a "make public in YouTube Studio" task. Apply for the audit (YouTube API Services audit form) to lift it.

### Instagram + Facebook
1. Convert Instagram to a **Professional** (Creator/Business) account; create a Facebook Page and link it.
2. developers.facebook.com → create app (Business) → add Instagram API + Facebook Login for Business.
3. Request permissions: `instagram_business_basic`, `instagram_business_content_publish`, `instagram_business_manage_insights`,
   `pages_manage_posts`, `pages_read_engagement`, `pages_show_list` (App Review needed for non-test users;
   your own accounts work in development mode as app roles).
4. Generate long-lived tokens → set `INSTAGRAM_USER_ID`, `INSTAGRAM_ACCESS_TOKEN`, `META_PAGE_ID`, `META_PAGE_ACCESS_TOKEN`.
5. Instagram **pulls** videos from a public URL, so configure S3-compatible storage (Cloudflare R2 recommended) and set the `S3_*` variables.

### TikTok
Default: **manual handoff**. The dashboard's Calendar shows "Download post package" (video, cover, caption,
disclosure) and a "Mark as posted" box where you paste the live URL. To automate it, either:
* apply for TikTok **Content Posting API** + audit (developers.tiktok.com), then set `TIKTOK_*` and
  `TIKTOK_APP_AUDITED=true` and `platforms.tiktok.publishing_mode: direct_post`, or
* use an already-audited third-party scheduler (choosing a paid service is your decision).

## Notifications
* Email: any SMTP (Gmail app password, Postmark, SES) → `SMTP_*`, `NOTIFY_EMAIL_TO`; then add `email` to
  `notifications.channels`.
* Telegram: create a bot with @BotFather, get your chat id → `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, add `telegram`.

## Decisions only you can make
1. Approve the brand name after a trademark/handle check (see `docs/decisions.md`).
2. Choose the brand voice in ElevenLabs.
3. Approve the first videos (supervised mode) and later, explicitly, `controlled` mode.
4. Approve any spending-cap increase, sponsorship, or new paid service.
