#!/usr/bin/env bash
# Remove staged zips and orphaned work dirs older than STAGE_RETENTION_HOURS (default 12).
# Schedule at 00:00 UTC daily, e.g. crontab with CRON_TZ=UTC.
set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"
export STAGE_WORK_PATH="${STAGE_WORK_PATH:-/home/peijin/tmpdir/work}"
export STAGE_READY_PATH="${STAGE_READY_PATH:-/home/peijin/tmpdir/ready}"
export STAGE_RETENTION_HOURS="${STAGE_RETENTION_HOURS:-12}"
python3 "$SCRIPT_DIR/cleanup_stage.py"
