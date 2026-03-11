#!/usr/bin/env bash
# Run append_dataset.py daily (e.g. from crontab at 04:00 UTC).
# Uses default starting_date = today - 3 days. Set LWA_DB_PATH if needed.
set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"
export LWA_DB_PATH="${LWA_DB_PATH:-$SCRIPT_DIR/lwa_data.db}"
python3 append_dataset.py
