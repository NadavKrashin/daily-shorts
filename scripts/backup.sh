#!/usr/bin/env bash
# Manual backup (the scheduler also runs `db_backup` nightly at 03:30 owner time).
set -euo pipefail
waitwhy backup
