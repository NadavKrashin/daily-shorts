# Why in Clay (automated animated-explainer studio)

> **Now produced with Higgsfield.** Episodes are made by scheduled Claude runs following
> [`channel/why-in-clay.md`](channel/why-in-clay.md) (Claymotion look, Kevin narration). This app handles approvals,
> publishing, analytics and reports, and runs in autonomous mode (`config/company.yaml`).

*The world is weirder than you think.* A production-minded system that discovers topics, researches and
fact-checks them, writes scripts, storyboards scenes, renders 60-second vertical animated explainers, runs
technical and editorial QC, publishes through official platform APIs after approval, tracks analytics and
money, and reports to the owner every morning.

> **Status (2026-10-15):** Phase 1 complete and tested. Runs end-to-end in **dry-run mode**, with no paid
> APIs and no real posting. Live research, licensed narration, AI hero shots and real publishing are built
> against the official APIs but need your credentials. See [docs/setup-guide.md](docs/setup-guide.md).

## The first video

`docs/demo/why-traffic-jams-appear-out-of-nowhere.mp4`: 57 s, 1080×1920, 30 fps, H.264/AAC, −14 LUFS,
burned-in captions + `captions.srt`, cover image, manifest. All 27 QC checks pass. It is marked
**not publishable** because the dry-run narration uses a free, **non-commercial** local voice. Re-rendering
with your ElevenLabs voice makes it publishable.

![contact sheet](docs/demo/contact-sheet.png)

The visuals come from a real car-following simulation (Intelligent Driver Model) set up like the
Sugiyama et al. 2008 ring-road experiment. The jam and its backward motion **emerge from the physics** and are
labelled "SIMULATION" on screen. Facts were checked against the primary paper. That check changed the script:
the backward speed is "roughly 15–20 km/h", not "15".

## Quick start (dev)

```bash
python3 -m venv .venv && . .venv/bin/activate && pip install -e ".[dev,localtts]"
cp .env.example .env                       # set DATABASE_URL, DASHBOARD_PASSWORD
waitwhy migrate && waitwhy init            # schema + org/brand + 36 scored backlog topics
waitwhy demo                               # full dry-run lifecycle for the traffic-jam explainer
waitwhy api                                # dashboard on http://localhost:8000
waitwhy worker & waitwhy scheduler &       # background processing + daily schedule (Asia/Jerusalem)
pytest                                     # 68 tests (SKIP_SLOW=1 skips the full-render test)
```

Docker: `cp .env.example .env && docker compose up -d --build` (see [docs/deployment.md](docs/deployment.md)).

## What's where

| Path | What |
|---|---|
| `config/company.yaml` | Central business config (budgets, modes, schedules, platforms, models, brand) |
| `waitwhy/pipeline.py` | Deterministic orchestration: the only place state changes |
| `waitwhy/states.py` | Workflow state machine (IDEA → … → ANALYZING, + NEEDS_REVISION/BLOCKED/FAILED/CANCELLED) |
| `waitwhy/jobs/` | Durable Postgres queue, worker, cron scheduler |
| `waitwhy/agents/` | COO, trends, research/fact-check, writer (script + storyboard), production (visuals + voice), editor, QC, metadata |
| `waitwhy/prompts/*.md` | 12 versioned prompt templates (version recorded on every agent run) |
| `waitwhy/media/` | Simulation, scene templates, captions, audio, FFmpeg render + probes |
| `waitwhy/providers/` | Claude, ElevenLabs, Piper (dev), Higgsfield, mock providers, local/S3 storage |
| `waitwhy/publishing/` | YouTube, Instagram, Facebook, TikTok (manual handoff), mock; idempotent publish service |
| `waitwhy/analytics/`, `business/`, `reports.py` | Metrics warehouse, cohorts, budget, finance, sponsors, CEO reports |
| `waitwhy/api/`, `waitwhy/web/` | Dashboard + JSON API |
| `seeds/` | Topic backlog and the hand-checked traffic-jam content pack |
| `docs/` | Architecture, technology selection & costs, implementation plan, setup, deployment, runbook, compliance, decisions |

## Safety defaults
Supervised mode (you approve every video), dry run on, auto-publish off, outreach sending off, $400 budget
with a $500 hard cap and $35 per-video ceiling, emergency **Pause all publishing** button, nothing ever deletes
live content, private uploads are never reported as published, unsupported metrics are stored as unknown (never 0).
