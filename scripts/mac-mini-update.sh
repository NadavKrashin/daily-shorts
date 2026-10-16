#!/bin/bash
# Auto-update for the native (no Docker) Mac mini install: pull main and, when anything the app runs
# on changed, reinstall/migrate/restart the launchd services co.whyinclay.{api,worker,scheduler}.
#
#   bash scripts/mac-mini-update.sh            # one update now (what launchd runs every 15 minutes)
#   bash scripts/mac-mini-update.sh --install  # install/refresh the co.whyinclay.update launchd service
#
# Episode data (channel/) and docs don't trigger a restart: the app reads channel/ on every import.
# If the install or a migration fails, the running services are left on the old version.
set -uo pipefail

DIR="$(cd "$(dirname "$0")/.." && pwd)"
STATE="$DIR/.git/deployed-rev"   # commit the running services were started from
UID_="$(id -u)"
SERVICES=(api worker scheduler)
export PATH="$DIR/.venv/bin:/opt/homebrew/opt/postgresql@16/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"

log() { printf '%s %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"; }

if [ "${1:-}" = "--install" ]; then
  PLIST="$HOME/Library/LaunchAgents/co.whyinclay.update.plist"
  mkdir -p "$DIR/logs" "$(dirname "$PLIST")"
  cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>co.whyinclay.update</string>
  <key>ProgramArguments</key><array><string>/bin/bash</string><string>$DIR/scripts/mac-mini-update.sh</string></array>
  <key>StartInterval</key><integer>900</integer>
  <key>StandardOutPath</key><string>$DIR/logs/update.log</string>
  <key>StandardErrorPath</key><string>$DIR/logs/update.log</string>
</dict></plist>
EOF
  plutil -lint "$PLIST" >/dev/null || { log "invalid plist $PLIST"; exit 1; }
  launchctl bootout "gui/$UID_/co.whyinclay.update" 2>/dev/null || true
  launchctl bootstrap "gui/$UID_" "$PLIST" || { log "could not load $PLIST"; exit 1; }
  log "installed co.whyinclay.update: runs $DIR/scripts/mac-mini-update.sh every 15 minutes"
  exit 0
fi

cd "$DIR" || { log "missing $DIR"; exit 1; }

if ! out=$(git pull --ff-only -q 2>&1); then
  log "git pull failed: $out"
  exit 1
fi

new="$(git rev-parse HEAD)"
old="$(cat "$STATE" 2>/dev/null || true)"
[ "$old" = "$new" ] && exit 0

if [ -z "$old" ] || ! git cat-file -e "$old^{commit}" 2>/dev/null; then
  changed="(unknown previous commit)"
else
  changed="$(git diff --name-only "$old" "$new" | grep -vE '^(channel/|docs/|\.claude/)|\.md$' || true)"
fi

if [ -z "$changed" ]; then
  log "updated ${old:0:7} -> ${new:0:7}: episode/docs changes only, no restart"
  echo "$new" > "$STATE"
  exit 0
fi

log "updated ${old:0:7} -> ${new:0:7}: app files changed, redeploying"
printf '%s\n' "$changed" | head -20 | sed 's/^/    /'

if [ "$changed" = "(unknown previous commit)" ] || grep -q '^pyproject.toml$' <<<"$changed"; then
  log "reinstalling package"
  pip install -q -e . || { log "pip install failed; services left on the old version"; exit 1; }
fi

log "running migrations"
if ! out=$(waitwhy migrate 2>&1); then
  log "migration failed; services left on the old version"
  printf '%s\n' "$out" | tail -20
  exit 1
fi

# SIGTERM lets the worker finish its current job; KeepAlive brings each one back on the new code.
for s in "${SERVICES[@]}"; do
  launchctl kill SIGTERM "gui/$UID_/co.whyinclay.$s" 2>/dev/null || launchctl kickstart "gui/$UID_/co.whyinclay.$s"
done

sleep 15   # let the old processes exit and launchd respawn them (ThrottleInterval 10)
for _ in $(seq 1 60); do
  if curl -fs localhost:8000/healthz >/dev/null 2>&1; then
    echo "$new" > "$STATE"
    log "restarted ${SERVICES[*]}; health check OK on ${new:0:7}"
    exit 0
  fi
  sleep 5
done
log "health check failed after restart on ${new:0:7}; see $DIR/logs/api.log"
exit 1
