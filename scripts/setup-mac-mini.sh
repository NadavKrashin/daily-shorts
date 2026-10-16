#!/bin/bash
# One-shot setup of the Why in Clay app on a Mac mini (see docs/deploy-mac-mini.md).
#
#   bash setup-mac-mini.sh
#
# Safe to re-run: every step checks what is already done and skips it. Stops with a clear message
# whenever it needs you (install Docker Desktop, add the deploy key on GitHub), then continue by
# running it again.
set -euo pipefail

REPO="git@github.com:NadavKrashin/daily-shorts.git"
BRANCH="main"   # the only branch; the scheduled runs push new episodes here
DIR="${REPO_DIR:-$HOME/daily-shorts}"
KEY="$HOME/.ssh/daily_shorts"

say()  { printf '\n\033[1m==> %s\033[0m\n' "$*"; }
stop() { printf '\n\033[1;31m%s\033[0m\n' "$*"; exit 1; }

[ "$(uname -s)" = "Darwin" ] || stop "This script is for macOS."

# ---------------------------------------------------------------- 1. tools
say "Checking tools"
command -v git >/dev/null || { xcode-select --install || true; stop "Install the Command Line Tools in the window that opened, then run this script again."; }
if ! command -v docker >/dev/null; then
  stop "Docker Desktop is not installed. Download it from https://www.docker.com/products/docker-desktop/ (Apple chip or Intel, matching this Mac), open it once, then run this script again."
fi
if ! docker info >/dev/null 2>&1; then
  open -a Docker || true
  printf 'Starting Docker Desktop'
  for _ in $(seq 1 60); do docker info >/dev/null 2>&1 && break; printf '.'; sleep 3; done
  echo
  docker info >/dev/null 2>&1 || stop "Docker Desktop did not start. Open it, accept its terms, then run this script again."
fi
echo "git and Docker are ready."

# ---------------------------------------------------------------- 2. deploy key + clone
if [ ! -d "$DIR/.git" ]; then
  say "Connecting to GitHub with a read-only deploy key"
  mkdir -p "$HOME/.ssh" && chmod 700 "$HOME/.ssh"
  [ -f "$KEY" ] || ssh-keygen -q -t ed25519 -f "$KEY" -N "" -C "mac-mini deploy key (daily-shorts)"
  if ! grep -q "$KEY" "$HOME/.ssh/config" 2>/dev/null; then
    printf '\nHost github.com\n  IdentityFile %s\n  IdentitiesOnly yes\n' "$KEY" >> "$HOME/.ssh/config"
    chmod 600 "$HOME/.ssh/config"
  fi
  if ! ssh -o StrictHostKeyChecking=accept-new -T git@github.com 2>&1 | grep -q "successfully authenticated"; then
    pbcopy < "$KEY.pub" 2>/dev/null || true
    echo "Add this key on GitHub (it is already on your clipboard):"
    echo
    cat "$KEY.pub"
    echo
    echo "  1. Open https://github.com/NadavKrashin/daily-shorts/settings/keys/new"
    echo "  2. Title: Mac mini.  Key: paste.  Leave 'Allow write access' OFF.  Click Add key."
    open "https://github.com/NadavKrashin/daily-shorts/settings/keys/new" || true
    stop "Then run this script again."
  fi
  say "Cloning the repository into $DIR"
  git clone -q -b "$BRANCH" "$REPO" "$DIR"
else
  say "Updating the existing checkout in $DIR"
  git -C "$DIR" pull -q --ff-only
fi
cd "$DIR"

# ---------------------------------------------------------------- 3. .env with fresh secrets
if [ ! -f .env ]; then
  say "Writing .env with new random secrets"
  rand() { openssl rand -hex 24; }
  PASS="$(rand)"
  HOST="$(scutil --get LocalHostName 2>/dev/null || hostname -s).local"
  while IFS= read -r line || [ -n "$line" ]; do
    case "$line" in
      APP_ENV=*)           echo "APP_ENV=production" ;;
      SECRET_KEY=*)        echo "SECRET_KEY=$(rand)" ;;
      DASHBOARD_PASSWORD=*) echo "DASHBOARD_PASSWORD=$PASS" ;;
      POSTGRES_PASSWORD=*) echo "POSTGRES_PASSWORD=$(rand)" ;;
      PUBLIC_BASE_URL=*)   echo "PUBLIC_BASE_URL=http://$HOST:8000" ;;
      *)                   echo "$line" ;;
    esac
  done < .env.example > .env
  chmod 600 .env
  printf '%s\n' "$PASS" > "$HOME/.why-in-clay-dashboard-password"
  chmod 600 "$HOME/.why-in-clay-dashboard-password"
  echo "Dashboard password saved to ~/.why-in-clay-dashboard-password (user: ceo)."
else
  echo ".env already exists; leaving it unchanged."
fi

# ---------------------------------------------------------------- 4. start the app
say "Building and starting the app (the first build takes a few minutes)"
docker compose up -d --build
printf 'Waiting for the app to answer'
ok=""
for _ in $(seq 1 60); do
  if curl -fs localhost:8000/healthz >/dev/null 2>&1; then ok=1; break; fi
  printf '.'; sleep 5
done
echo
docker compose ps
[ -n "$ok" ] || stop "The app did not become healthy in 5 minutes. Send the output of: docker compose logs --tail 80"
echo "Health check passed: http://localhost:8000"

# ---------------------------------------------------------------- 5. pull new episodes every 15 min
say "Scheduling a git pull every 15 minutes (new episodes)"
LINE="*/15 * * * * cd $DIR && /usr/bin/git pull --ff-only -q"
if crontab -l 2>/dev/null | grep -qF "$DIR && /usr/bin/git pull"; then
  echo "Already scheduled."
else
  ( crontab -l 2>/dev/null; echo "$LINE" ) | crontab -
  echo "Added: $LINE"
fi

# ---------------------------------------------------------------- 6. stay awake
say "Keeping the Mac awake and restarting after power cuts (asks for your Mac password)"
sudo pmset -a sleep 0 disksleep 0 autorestart 1 || echo "Skipped. Set it later in System Settings > Energy."

# ---------------------------------------------------------------- 7. first import
say "Importing the episodes made so far"
docker compose exec -T worker waitwhy import-episodes || echo "Import will run on its own within 30 minutes."

say "Done. Two settings only you can change:"
cat <<'EOF'
  1. Docker Desktop > Settings > General: turn on "Start Docker Desktop when you sign in".
  2. System Settings > Users & Groups: "Automatically log in as" this user (needs FileVault off),
     so the app comes back by itself after a power cut.

Dashboard: http://localhost:8000  (user: ceo, password in ~/.why-in-clay-dashboard-password)
Check tomorrow: Dashboard > Agents shows a fresh scheduler heartbeat and the 09:00 report.
EOF
