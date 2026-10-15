# Operations runbook

## Daily (2 minutes, from your phone)
1. Read the 09:00 report (email/Telegram, or Dashboard → Overview).
2. **Approvals**: watch each pending video, then Approve / Request changes / Reject.
3. **Calendar → Needs your action**: post TikTok packages manually and paste the live URL ("Mark as posted").
4. **Incidents**: acknowledge anything high/critical, adding a one-line resolution.

## Emergency controls
* **Pause all publishing**: red button in the header. Takes effect at the next job claim. Uploads already in flight finish.
* **Pause automation**: Settings → Pause automation. Only health checks, reports, analytics and recovery keep running.
* Nothing in the system deletes or unpublishes live content. Do that manually on the platform if ever needed.

## Common incidents

| Symptom | Likely cause | Action |
|---|---|---|
| "Scheduler heartbeat missing" | scheduler container down | `docker compose up -d scheduler`; missed daily jobs run once automatically (6 h catch-up) |
| "No live workers" | worker crashed / OOM | `docker compose logs worker`; `docker compose up -d worker`; stalled jobs are re-queued automatically |
| "<platform> integration disconnected" | token expired/revoked | regenerate token, update `.env`, `docker compose up -d`; Agents → retry the dead `publish` job |
| "Verify <platform> upload" | worker died mid-upload | check the platform: if the post exists, use "Mark as posted"; if not, retry the job |
| "Spending approval needed" | monthly cap or per-video ceiling reached | Approvals → approve or reject; approving resumes parked jobs without regenerating finished work |
| Video in NEEDS_REVISION | a QC gate failed | open the video → QC panel lists blocking issues → "Request changes" from the right stage (Re-edit reuses all assets) |
| Video BLOCKED "no public publication yet" | only private/manual results | make it public in YouTube Studio / post manually, then "Mark as posted" |
| YouTube uploads always private | API project not audited | expected until audit; publish in Studio |
| Report says metrics UNKNOWN | analytics scope/token missing | reconnect with analytics scopes |
| "Major factual error after publication" | — | **Critical**: pause publishing; edit description with a correction or unpublish manually; record an incident; add the error to the fact sheet's misleading simplifications |

## Incident procedure
Detect (alert) → classify (severity) → retry only if transient (automatic, bounded) → capture logs
(`docker compose logs --since 1h <svc>`) → apply recovery → escalate if it fails → record the resolution in
Incidents. Never delete an incident.

## Backups & restore drill (monthly)
```bash
docker compose exec worker waitwhy backup                 # on-demand backup
createdb waitwhy_restore_test
DATABASE_URL=postgresql://.../waitwhy_restore_test scripts/restore.sh backups/waitwhy-<stamp>.dump
```
Check the row counts in `videos` and `publication_jobs`, then drop the test database.

## Useful commands
```bash
waitwhy produce "Why Golf Balls Have Dimples" --category science_physics   # start a video now
waitwhy run                    # process queued jobs in the foreground (debugging)
waitwhy report                 # print today's CEO report
waitwhy tick                   # enqueue due scheduled jobs once
waitwhy approve <slug>         # approve from the CLI
```

## Logs & monitoring
Logs are structured JSON lines on stdout (`docker compose logs`). Health endpoint: `GET /healthz`. Point an
uptime monitor (UptimeRobot, Better Stack) at it, and Sentry can be added via `SENTRY_DSN` later.
