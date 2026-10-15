# Implementation plan & status

Legend: ✅ built and tested here · 🟡 built, needs your credentials/accounts to verify live · ⬜ not started

## Phase 1: working local prototype ✅
| Deliverable | Status |
|---|---|
| Repo, Docker Compose, Postgres schema (31 tables) + Alembic migration (up/down tested) | ✅ (Compose not run here, no Docker daemon) |
| Backend API + dashboard | ✅ |
| Topic generation (seed backlog of 36 scored topics + LLM discovery with dedupe) | ✅ / 🟡 LLM discovery |
| Research & fact-check workflow with source gates | ✅ logic · 🟡 live research needs `ANTHROPIC_API_KEY` |
| Script + storyboard generation with validators | ✅ logic · 🟡 live generation needs key |
| Deterministic animation engine (IDM traffic sim, 13 templates) | ✅ |
| Narration (ElevenLabs adapter; Piper dev voice) | ✅ dev voice · 🟡 ElevenLabs |
| FFmpeg assembly, captions (ASS + SRT), loudness, thumbnail | ✅ |
| Technical + editorial QC | ✅ (multimodal LLM review 🟡) |
| Mock publishing connectors | ✅ |
| **"Why Traffic Jams Appear Out of Nowhere": complete 55 s render** | ✅ technically valid; *not publishable* only because of the non-commercial dev voice |

## Phase 2: production automation 🟡
Scheduled research, backlog upkeep, retries, history, approvals UI, cost accounting, storage: ✅ built.
Real video provider (Higgsfield API) and voice (ElevenLabs): 🟡 adapters written against the official docs but
not exercised (no API keys in the build environment). **Next step:** add keys, run `waitwhy produce` for 3 topics,
compare costs to estimates.

## Phase 3: publishing 🟡
YouTube / Instagram / Facebook adapters, TikTok manual handoff, scheduling, idempotency, approval gates: ✅ built and
tested with mock adapters (independent per-platform status, duplicate prevention, interrupted upload, expired auth).
**Success criterion ("verified end-to-end test on one authorised platform") is not met yet.** It needs the YouTube OAuth
setup. The first live test should be a **private** upload of the traffic video re-rendered with the licensed voice.

## Phase 4: analytics & intelligence 🟡
Ingestion (NULL-not-zero), windows 24h/72h/7d/30d, per-platform baselines, cohort medians with sample-size flags,
experiment log, strategy analysis, daily/weekly/monthly reports: ✅. Needs real posts to produce real data.

## Phase 5: business operations ✅
Budget enforcement (monthly cap, per-video ceiling, 50/80/95 % alerts, approval-to-resume), expenses/revenue
ledgers (cash/accrued/estimated; expected/invoiced/received), P&L, sponsor pipeline with drafts only, rate guidance
(refuses below 5 data points), weekly/monthly reports.

## Phase 6: controlled autonomy 🟡
Persistent schedules, worker heartbeats, stalled-job recovery, orphan recovery, incident alerts, backups (tested),
operating modes with policy-based auto-approval (never for sponsored, high-risk or non-publishable content) ✅.
**Must be verified on your server:** scheduler and workers running unattended for 48 h, with health checks and reports observed.

## Next engineering steps (priority order)
1. Live provider smoke tests once keys exist: Claude research on 3 seeded topics, ElevenLabs voice, one Higgsfield clip.
2. YouTube private-upload test, then Instagram and Facebook with test accounts.
3. YouTube/Facebook post-processing re-verification job (today: alert after 2 h "processing").
4. More programmatic template families (maps/great-circle routes, probability trees, signal/waves, orbit diagrams)
   so most backlog topics can be produced without generative video.
5. Sentry/OpenTelemetry error monitoring; Prometheus metrics endpoint.
6. Per-scene targeted repair UI (regenerate scene N only). The data model and cache keys already support it.
