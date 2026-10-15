#!/usr/bin/env bash
# Restore a pg_dump custom-format backup INTO AN EMPTY DATABASE. Stop api/worker/scheduler first.
# usage: scripts/restore.sh backups/waitwhy-YYYYMMDDTHHMMSSZ.dump
set -euo pipefail
FILE=${1:?backup file}
: "${DATABASE_URL:?set DATABASE_URL}"
URL=${DATABASE_URL/postgresql+psycopg/postgresql}
read -r -p "Restore $FILE into $URL ? This overwrites data. Type RESTORE: " ok
[ "$ok" = "RESTORE" ] || exit 1
pg_restore --clean --if-exists --no-owner -d "$URL" "$FILE"
echo "restored; run 'waitwhy migrate' to apply any newer migrations"
