# Deployment guide

## Option A (recommended): one small Linux VM + Docker Compose

Sizing: 4 vCPU / 8 GB RAM / 80 GB disk handles 20+ videos/month (a 60-s render takes about 2–3 CPU-minutes).

```bash
# on the server (Ubuntu 24.04)
sudo apt-get update && sudo apt-get install -y docker.io docker-compose-v2 git
git clone <your repo> waitwhy && cd waitwhy
cp .env.example .env && chmod 600 .env     # fill in secrets (see setup-guide.md)
#   APP_ENV=production, DASHBOARD_PASSWORD=<long random>, SECRET_KEY=<long random>, POSTGRES_PASSWORD=<random>
docker compose up -d --build                # db -> migrate+init -> api, worker, scheduler
docker compose ps && curl -fs localhost:8000/healthz
```

Put TLS in front, using Caddy (automatic HTTPS) for example:

```
ops.example.com {
    reverse_proxy localhost:8000
}
```

Set `PUBLIC_BASE_URL=https://ops.example.com`. Restrict the dashboard further with Caddy `basicauth`, a VPN,
or Cloudflare Access if you like.

### Verify the automation is really running
1. `docker compose logs -f scheduler worker`: you should see heartbeats and the `*/5` jobs every 5 minutes.
2. Dashboard → **Agents**: scheduler heartbeat less than 1 min old, at least 1 worker listed.
3. Next morning: the 07:00 health check and 09:00 report appear under Agents and Overview.
Do not consider the business "running" until you have seen those three things.

### Scaling
`docker compose up -d --scale worker=2`: the queue is safe for many workers. Rendering concurrency is capped
by the job spec (`edit: concurrency=1`). Raise it only if the VM has spare CPU.

### Backups
* Nightly `db_backup` at 03:30 (owner time) writes `pg_dump -Fc` files to the `backups` volume. 14 are kept, and they are
  uploaded to `s3://$S3_BUCKET/backups/` when S3 is configured.
* Media lives in the `media` volume (or S3). Back up S3 with bucket versioning or lifecycle rules.
* **Test a restore monthly** (see runbook).

### Upgrades
```bash
git pull && docker compose build && docker compose up -d   # `migrate` service applies Alembic migrations first
```

## Option B: managed containers (Fly.io / Render / Railway / ECS)
Run the same image three times with commands `waitwhy api`, `waitwhy worker` and `waitwhy scheduler`, against a managed
Postgres (Neon, Supabase, RDS) and S3-compatible storage (`providers.storage: s3`). Run `waitwhy migrate && waitwhy init`
as a release command. Keep exactly one scheduler. Extra schedulers are harmless thanks to idempotent slots, but wasteful.

## Bare metal (no Docker)
Python 3.12+, FFmpeg ≥ 6 with libass, Postgres 16, Inter font. `pip install .`, then run the three processes
under systemd. Same commands as above.

## Status of this deployment
The Compose file and Dockerfile are written but were **not executed in the build environment** (no Docker daemon
there). The application itself was run and tested natively against PostgreSQL 16 and FFmpeg 6.1. Run
`docker compose up --build` once on your server and check `/healthz` before relying on it.
