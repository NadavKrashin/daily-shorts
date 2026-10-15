# Technology selection & cost estimate

Researched **2026-10-15**. Prices change often. Every figure below is an estimate to re-check on the
vendor's live pricing page before you commit money. Where only third-party sources were found, that is stated.

## Stack

| Layer | Choice | Why |
|---|---|---|
| Language / API | Python 3.12+, FastAPI, Pydantic v2, SQLAlchemy 2, Alembic | Requested stack; typed contracts between agents |
| Database | PostgreSQL 16 | State, lineage, queue, analytics, finance in one place; JSONB for structured agent output |
| Workflow engine | Postgres-backed queue + explicit state machine (no n8n) | One fewer service; transactional with the data it moves; easy to test. See D-002 |
| Scheduler | Built-in cron evaluator, idempotent per slot | Restart-safe, multi-instance-safe, catches up missed slots once |
| Dashboard | Server-rendered Jinja + plain CSS + Chart.js (pinned CDN) | One deployable, works on phone, no JS build chain. See D-003 |
| Media | FFmpeg 6, libass, Pillow + NumPy renderer, IDM traffic simulation | Deterministic, cheap, consistent; exact narration sync |
| Storage | Local disk (dev) / any S3-compatible bucket (prod: Cloudflare R2, Backblaze B2, AWS S3) | Instagram must pull a public URL; S3 presigned URLs solve that |
| Deploy | Docker Compose on one small VM | Portable; no Kubernetes needed at this scale |

## Providers: what was verified

| Need | Provider | Verified facts | Status in code |
|---|---|---|---|
| LLM (research, fact-check, scripts, storyboards, QC) | **Anthropic Claude API**: `claude-opus-5-5` ($4 / $20 per M tokens) for reasoning tasks, `claude-haiku-5-5` ($0.10 / $0.50) for formatting/classification; server-side `web_search` ($10 per 1k searches) | Model IDs and prices from Anthropic's model table (2026-10-06). Structured outputs via JSON schema; refusal fallbacks enabled | `providers/llm_anthropic.py`. **Needs `ANTHROPIC_API_KEY`** |
| Narration | **ElevenLabs** (you have an account) | Commercial use requires a **paid** plan (free tier is non-commercial). Third-party sources put Starter at about $5–6/mo for 30k credits and Creator at about $22/mo for 100k–121k credits. They disagree, so verify. API usage draws on the same account credits. `/with-timestamps` gives word timings | `providers/tts.py::ElevenLabsTTS`. **Needs API key + licensed voice ID** |
| Images / video clips | **Higgsfield API** (you have an account) | Official: self-serve API at api.higgsfield.ai, `Authorization: Key id:secret`, model chosen by URL path, async request IDs, statuses `queued/in_progress/completed/failed/nsfw/canceled`, outputs kept ≥7 days, **commercial use permitted**, failed requests not billed, 20 concurrent requests. **API wallet is separate from web-app credits** (pay-as-you-go, $5 min top-up per third-party review). Example: Kling 2.6 ≈ $0.07/s | `providers/mediagen.py::HiggsfieldAPI`. **Needs API key + top-up; set verified video model path** |
| Avatar video | HeyGen (you have an account) | API billed from a separate wallet; third-party sources put Avatar/Video Agent at about $2–6/min. A talking-avatar format doesn't fit the animated-explainer brand | **Not used** initially (no adapter). Optional later for a presenter format |
| Dev voice | Piper (local, free) | The suggested `en_US-ryan-high` voice is trained on **CC BY-NC-SA** data, so it is **non-commercial** | Used only for dry runs. QC marks such videos **not publishable** |

The Higgsfield **MCP connector** in Claude chat sessions is a different access path. The backend needs
its own API key from https://open.higgsfield.ai.

## Platforms: what was verified (official docs)

| Platform | Finding | Implementation |
|---|---|---|
| YouTube | `videos.insert` (resumable). Uploads from **unverified API projects created after 2020-07-28 are locked to private** until a compliance audit passes. `status.containsSyntheticMedia` exists for realistic altered content. Default quota 10,000 units/day; per-upload cost differs between doc mirrors, so check the Cloud Console | Uploads, then **reads back** the real privacy. A private result is recorded as `private_uploaded` plus a manual action, never as published |
| Instagram | `POST /{ig-user-id}/media` (`media_type=REELS`, public `video_url`) → poll `status_code` → `media_publish`. Professional account required. 100 API posts / 24 h (an older page says 50) | Implemented. Needs public media URL (S3/R2) |
| Facebook | Pages Reels API: `video_reels` start → upload to `rupload.facebook.com` (`Authorization: OAuth`) → finish `video_state=PUBLISHED`. 3–90 s, 9:16, 30 API reels / 24 h | Implemented |
| TikTok | Content Posting API: **unaudited clients may only post to private accounts**, and public direct posts are blocked (`unaudited_client_can_only_post_to_private_accounts`). Audit required | **Manual handoff** (download package + "mark as posted"). Direct-post adapter ships disabled until `TIKTOK_APP_AUDITED=true`. Alternatives: an already-audited scheduler (Buffer, Later, Hootsuite, Blotato). Higgsfield also advertises TikTok publishing in its connector, worth evaluating |

## Expected recurring cost (20 videos / month, estimates)

| Item | Basis | Est. USD / month |
|---|---|---|
| Claude API | about $1.2–1.8 per video (research with ~8 searches, fact-check, script with one rewrite, storyboard, multimodal QC; metadata on Haiku) plus about $5 for trends, strategy and reports | **$30–45** |
| ElevenLabs | Creator tier covers about 20 × ~1k characters × retakes | **$22** (verify plan) |
| Higgsfield | ≤ 4 AI clips × 5 s × $0.07–0.10/s per video (many videos will use 0) | **$0–40** |
| VM (4 vCPU / 8 GB, renders take about 2–3 min/video) | Hetzner / DigitalOcean / Lightsail class | **$10–40** (verify) |
| Object storage (R2/B2) | < 5 GB with assets | **< $1** |
| Email / Telegram notifications | free tiers | **$0** |
| **Total** | | **≈ $65–150 / month**, well under the $400 budget |

The default per-video production target is $20 against an expected **$2–8** actual cost. The remaining
budget is headroom for more AI hero shots once data shows they improve retention.
Budget enforcement: monthly hard cap $500 (variable spend), per-video ceiling $35, alerts at 50/80/95 % of $400.
