# Decision log & assumptions

| ID | Date | Decision | Rationale | Revisit when |
|---|---|---|---|---|
| D-001 | 2026-10-15 | Python monorepo, one Docker image for api/worker/scheduler | Smallest operational surface for a solo owner | Team grows / services need independent scaling |
| D-002 | 2026-10-15 | Postgres job queue (SKIP LOCKED) instead of n8n/Temporal | Transactional with app data; retries, idempotency, dead-letter, recovery all testable in-process; no extra infra. n8n can still call `/api/jobs/*` | Many external SaaS integrations needed, or multi-day workflows with complex compensation |
| D-003 | 2026-10-15 | Server-rendered dashboard (Jinja + CSS + Chart.js) instead of Next.js | One deployable, no JS build, fast on mobile; dashboard is CRUD + charts | Need rich client interactivity or a public-facing site |
| D-004 | 2026-10-15 | Deterministic motion graphics by default; generative video only for ≤4 hero shots | Cost, consistency, scientific faithfulness (no hallucinated diagrams) | Data shows AI hero shots lift retention enough to pay for themselves |
| D-005 | 2026-10-15 | Traffic visuals driven by an Intelligent Driver Model simulation, labelled "SIMULATION" | The jam and its backward motion emerge from physics, not from an illustrator's guess; satisfies "no fake demonstrations" | — |
| D-006 | 2026-10-15 | Dry-run waivers: QC records dev stand-ins (mock content, non-commercial voice) as waivers and marks the version `publishable=false` | Lets the whole lifecycle be exercised safely, while the live publisher and scheduler refuse such versions | — |
| D-007 | 2026-10-15 | TikTok = manual handoff | Content Posting API requires an audit; unaudited clients can't post publicly. We never bypass that | App passes TikTok audit, or an audited scheduler is chosen |
| D-008 | 2026-10-15 | Unsupported metrics stored as NULL, never 0; platform views never summed into "viewers" | Honest analytics | — |
| D-009 | 2026-10-15 | Audience-timezone publishing slots (US Eastern) rotating 12:00 / 17:00 / 19:30 weekdays | Owner timezone ≠ audience; start with reasonable defaults, learn from data | ≥ 20 posts per platform with 7-day data |
| D-010 | 2026-10-15 | Script facts must cite fact-sheet claim IDs; numbers without citations fail the script gate | Numbers are where errors hide | — |
| D-011 | 2026-10-15 | Spending approvals are written in their own DB transaction | The stage transaction is rolled back when a job parks; the approval request must survive (bug found by `test_budget_exhausted_halfway…`) | — |
| D-012 | 2026-10-15 | Videos are produced by scheduled Claude runs with Higgsfield, not the in-app renderer | The owner preferred the Higgsfield output; the recipe is `channel/why-in-clay.md`. The app keeps approvals, publishing and analytics | Owner |
| D-013 | 2026-10-15 | Channel renamed **Why in Clay**; look = Claymotion preset, narrator = Kevin | Owner picked Kevin + Claymotion from the audition and asked for a unique name containing "clay". @whyinclay was free on YouTube; Clayplained, Clay Curious, clay why and ClaySics were taken | Owner |
| D-014 | 2026-10-15 | Operating mode switched to autonomous | Owner: "I need this to be automatic." Production spends credits without asking (cap 200 credits per episode, pause under 200 balance). Real-money spend, account connections and sponsorships stay with the owner | Owner |

## Assumptions (to confirm)

* **"Why in Clay" has had a handle check only** (YouTube free, TikTok not found on 2026-10-15). No trademark search
  yet. The owner still has to claim the handles. A similar new channel, "Smush Science" (@SmushScience), makes clay
  science videos.
* The ElevenLabs account will be on a paid plan that grants commercial rights, with a stock/designed voice.
* Higgsfield API funds are separate from the web subscription, so a top-up is needed for API use.
* Audience: English-speaking 16–35. Demographics stay unverified until platform analytics arrive.

## Content facts corrected during research

* The traffic script originally said jams drift backwards at "15 km/h". The primary source (Sugiyama 2008) reports
  about **20 km/h**; highway studies report about 15 ± 5 km/h. The script now says "roughly fifteen to twenty", and the
  fact sheet records all three sources.

## D-015 On-screen text and diagrams are drawn in code, over the clay scenes (2026-10-16)
The owner asked for more text and explanatory animation. Video models garble lettering, so the clay
scenes stay text-free. `channel/tools/overlays.py` draws cards, count-up stats, cause-and-effect chains
and diagrams, timed to the narration through the caption timings. It costs no credits, every word is
spelled exactly, and the traffic diagrams come from a real car-following model (optimal velocity,
Bando et al. 1995) rather than hand-drawn motion.

## D-016 The app imports episodes instead of producing them (2026-10-16)
`production_source: claude_runs` keeps the built-in research/script/render pipeline idle. The
`import_episodes` job (every 30 min) turns `channel/episodes.json` entries into videos:
- technical QC with the same ffprobe checks as before, against the episode format (1440x2560, 24 fps, -16 LUFS);
- the run's own recorded checks (strict narration, captions, frame-strip review) must say `passed`;
- the same auto-approval gate as before (QC passed, score of at least 90, autonomous mode), then scheduling.

A new cut replaces a version only before approval. A late cut raises an alert instead of swapping a
scheduled video.

## D-017 Higgsfield output rights (2026-10-16)
Higgsfield's help center (checked 2026-10-16) says users own their outputs and the Terms of Use
(section 4.4) don't restrict commercial use, on any plan. The account is on the paid Plus plan.
Recorded as `episodes.higgsfield_commercial_use_confirmed: true`; setting it to `false` blocks publishing.

