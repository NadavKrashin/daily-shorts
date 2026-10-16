# Running the app on a Mac mini

The Mac mini runs the whole app: dashboard, worker, scheduler and Postgres, all in Docker. Videos are
still made in the cloud by the scheduled Claude runs. The Mac imports each finished episode and handles
publishing, analytics and the daily reports.

You need any Apple Silicon or Intel Mac mini with at least 8 GB RAM and 30 GB free disk, on macOS 14 or
newer, plugged into power and the internet.

## 1. Keep the Mac awake and self-restarting (5 minutes)

1. Open System Settings → Energy (on older macOS: Energy Saver). Turn on **Prevent automatic sleeping
   when the display is off** and **Start up automatically after a power failure**.
2. In Terminal, turn off sleep completely:
   `sudo pmset -a sleep 0 disksleep 0 displaysleep 10`
3. Docker Desktop only runs while a user is logged in. Turn on **automatic login** for this user:
   System Settings → Users & Groups → Automatically log in as. FileVault must be off for this option
   to appear. If you'd rather keep FileVault on, after every power cut you will need to log in once by
   hand.

## 2. Install the tools (10 minutes)

1. Install **Docker Desktop for Mac** from docker.com. Pick the Apple chip or Intel build to match your
   Mac. It is free for personal use and small businesses (check docker.com for the current terms).
2. In Docker Desktop, open Settings → General and turn on **Start Docker Desktop when you sign in**.
   In Settings → Resources, give it at least 4 CPUs and 6 GB of memory.
3. Install git. Running `git --version` in Terminal offers to install the Command Line Tools if it is
   missing.

## 3. Get the code (5 minutes)

The repository is private, so give the Mac its own read-only key:

```bash
ssh-keygen -t ed25519 -f ~/.ssh/daily_shorts -N "" -C "mac-mini deploy key"
cat ~/.ssh/daily_shorts.pub
```

Add the printed line on GitHub: repo → Settings → Deploy keys → Add deploy key. Leave write access off.
Then:

```bash
printf 'Host github.com\n  IdentityFile ~/.ssh/daily_shorts\n' >> ~/.ssh/config
cd ~ && git clone -b claude/happy-cannon-dzuzwj git@github.com:NadavKrashin/daily-shorts.git
cd ~/daily-shorts
```

Clone into your home folder (`~/daily-shorts`), not Documents or Desktop. macOS blocks background jobs
from those folders. Use the `claude/happy-cannon-dzuzwj` branch: the scheduled runs push each new
episode there, and `main` is only a snapshot.

## 4. Configure and start (5 minutes)

```bash
cp .env.example .env && chmod 600 .env
open -e .env
```

Set these values in `.env`:
- `APP_ENV=production`
- `DASHBOARD_PASSWORD`, `SECRET_KEY` and `POSTGRES_PASSWORD`: long random strings. `openssl rand -hex 24`
  makes one.
- `PUBLIC_BASE_URL=http://<the Mac's name>.local:8000` (or the Tailscale address from step 6).

Then start everything:

```bash
docker compose up -d --build
docker compose ps
curl -fs localhost:8000/healthz && echo OK
```

Open http://localhost:8000 and log in with `DASHBOARD_USERNAME` (default `ceo`) and your password.
Every service has `restart: unless-stopped`, so the app comes back whenever Docker Desktop starts.

## 5. Pull new episodes automatically

```bash
( crontab -l 2>/dev/null; echo '*/15 * * * * cd $HOME/daily-shorts && /usr/bin/git pull --ff-only -q' ) | crontab -
```

Every 15 minutes the Mac pulls new episodes, and the app imports them within 30 minutes. To import
right away, run `docker compose exec worker waitwhy import-episodes`.

## 6. Reach the dashboard from your phone (optional, free)

The Mac doesn't need to be reachable from the internet. Platforms receive uploads from it, and
Instagram and Facebook fetch videos from the R2 bucket (setup guide step 5), not from the Mac.

To see the dashboard away from home, install **Tailscale** on the Mac and on your phone and sign in
to both. Then open `http://<mac-name>:8000` from anywhere. Don't forward port 8000 on your router.

## 7. Check it is really running

Over the first day, confirm these three things:
1. `docker compose logs --tail 50 scheduler worker` shows heartbeats and jobs every 5 minutes.
2. Dashboard → Agents shows a scheduler heartbeat under a minute old and at least one worker.
3. The 07:00 health check and the 09:00 daily report appear the next morning.

## Updating and backups

- Code updates arrive with the same `git pull`. To rebuild after one, run
  `cd ~/daily-shorts && docker compose up -d --build`.
- The database is backed up nightly into a Docker volume. With R2 configured, the backups also go to
  `s3://<bucket>/backups/`, so they survive if the Mac's disk fails.
- After a power cut the Mac restarts, logs in, starts Docker and then the app. The scheduler runs any
  report or publish slot missed in the last 6 hours.
