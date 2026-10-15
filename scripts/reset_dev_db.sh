#!/usr/bin/env bash
# DEV ONLY: drop and recreate the local database, then migrate. Refuses to run in production.
set -euo pipefail
[ "${APP_ENV:-development}" = "production" ] && { echo "refusing in production"; exit 1; }
DB=${1:-waitwhy}
psql -h "${PGHOST:-127.0.0.1}" -U "${PGUSER:-postgres}" -c "DROP DATABASE IF EXISTS $DB;" -c "CREATE DATABASE $DB;"
DATABASE_URL=${DATABASE_URL:-postgresql+psycopg://postgres@127.0.0.1:5432/$DB} waitwhy migrate
