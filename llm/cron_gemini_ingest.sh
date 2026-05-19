#!/usr/bin/env bash
# Daily Gemini ingest for the last two UTC calendar days (yesterday + today).
# Schedule at 09:00 UTC, e.g. crontab with CRON_TZ=UTC.
#
# Requires GEMINI_API_KEY in the environment (or export in crontab).
set -e
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"
PYTHON="${PYTHON:-/home/peijin/miniconda3/envs/solarml/bin/python}"
export PYTHONUNBUFFERED=1
export LWA_DB_PATH="${LWA_DB_PATH:-$REPO_ROOT/dbscripts/lwa_data.db}"
export AI_SUMMARY_DB_PATH="${AI_SUMMARY_DB_PATH:-$REPO_ROOT/llm/ai_summary.db}"

if [ -z "${GEMINI_API_KEY:-}" ]; then
  echo "[ERROR] GEMINI_API_KEY is not set" >&2
  exit 1
fi

MIN_DATE="$(date -u -d '1 day ago' +%Y-%m-%d)"
MAX_DATE="$(date -u +%Y-%m-%d)"

echo "[INFO] Gemini ingest window: ${MIN_DATE} .. ${MAX_DATE} (UTC)"

exec "$PYTHON" "$REPO_ROOT/llm/run_gemini_injest_all_lwa_db_dates.py" \
  --min-date "$MIN_DATE" \
  --max-date "$MAX_DATE"
