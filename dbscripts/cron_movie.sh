#!/usr/bin/env bash
# Generate yesterday's daily OVRO-LWA image movie from cron.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_FILE="/tmp/cron_lwa.log"
PYTHON="${PYTHON:-python3}"

{
  echo "[$(date -Is)] START cron_movie"

  movie_date="$(date -u -d "yesterday" +%Y-%m-%d)"
  "$PYTHON" "$SCRIPT_DIR/generate_daily_movie.py" \
    --start "$movie_date" \
    --end "$movie_date"

  echo "[$(date -Is)] DONE cron_movie"
} >> "$LOG_FILE" 2>&1
