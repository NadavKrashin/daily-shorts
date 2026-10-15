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

## Assumptions (to confirm)

* **Brand name "Wait, Why?" is a working title.** Trademark, domain and handle availability have **not** been checked
  (needs a USPTO/EUIPO search and handle checks on all four platforms). Owner approval required before committing.
* Owner wants supervised mode (human approval of every video) for at least the first 20 videos.
* The ElevenLabs account will be on a paid plan that grants commercial rights, with a stock/designed voice.
* Higgsfield API funds are separate from the web subscription, so a top-up is needed for API use.
* Audience: English-speaking 16–35. Demographics stay unverified until platform analytics arrive.

## Content facts corrected during research

* The traffic script originally said jams drift backwards at "15 km/h". The primary source (Sugiyama 2008) reports
  about **20 km/h**; highway studies report about 15 ± 5 km/h. The script now says "roughly fifteen to twenty", and the
  fact sheet records all three sources.
