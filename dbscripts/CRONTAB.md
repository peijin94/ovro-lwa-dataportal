# Crontab: daily DB append at 04:00 UTC

Append new records every day at 4 UTC with `starting_date = today - 3` (only last 3 days).

**Install:**

1. Make the script executable:
   ```bash
   chmod +x /home/peijin/ovro-lwa-dataportal/dbscripts/cron_append.sh
   ```

2. Add to your crontab (`crontab -e`):
   ```cron
   0 4 * * * /home/peijin/ovro-lwa-dataportal/dbscripts/cron_append.sh >> /var/log/lwa_append.log 2>&1
   ```
   Or if you prefer a log file under the project:
   ```cron
   0 4 * * * /home/peijin/ovro-lwa-dataportal/dbscripts/cron_append.sh >> /home/peijin/ovro-lwa-dataportal/dbscripts/append.log 2>&1
   ```

3. Optional: set `LWA_DB_PATH` in the crontab environment if the DB is not in `dbscripts/`:
   ```cron
   0 4 * * * LWA_DB_PATH=/path/to/lwa_data.db /home/peijin/ovro-lwa-dataportal/dbscripts/cron_append.sh >> /var/log/lwa_append.log 2>&1
   ```

The script runs `python append_dataset.py` with no args, so `--starting_date` defaults to **today - 3 days** (UTC).

---

# Crontab: daily staging cleanup at 00:00 UTC

Remove finished zip bundles in `STAGE_READY_PATH` and orphaned trees in `STAGE_WORK_PATH` older than **12 hours** (by file mtime).

**Install:**

1. Make the script executable:
   ```bash
   chmod +x /home/peijin/ovro-lwa-dataportal/dbscripts/cron_cleanup_stage.sh
   ```

2. Add to your crontab (`crontab -e`). Use `CRON_TZ=UTC` so 00:00 is UTC:
   ```cron
   CRON_TZ=UTC
   0 0 * * * /home/peijin/ovro-lwa-dataportal/dbscripts/cron_cleanup_stage.sh >> /home/peijin/ovro-lwa-dataportal/dbscripts/stage_cleanup.log 2>&1
   ```

3. Optional env (same as the backend):
   ```cron
   0 0 * * * STAGE_WORK_PATH=/path/work STAGE_READY_PATH=/path/ready STAGE_RETENTION_HOURS=12 /home/peijin/ovro-lwa-dataportal/dbscripts/cron_cleanup_stage.sh >> /var/log/lwa_stage_cleanup.log 2>&1
   ```

Runs `dbscripts/cleanup_stage.py`, which reads paths from `backend/config.py` (overridable via `STAGE_WORK_PATH`, `STAGE_READY_PATH`).

---

# Crontab: daily movie generation at 02:30 UTC

Generate yesterday's daily synoptic image movie once per day, after the UTC day has completed.

**Install:**

1. Make the script executable:
   ```bash
   chmod +x /home/peijin/ovro-lwa-dataportal/dbscripts/cron_movie.sh
   ```

2. Add to your crontab (`crontab -e`):
   ```cron
   30 2 * * * flock -n /tmp/run_queryweb_movie_daily.lock /bin/bash -l /home/peijin/ovro-lwa-dataportal/dbscripts/cron_movie.sh
   ```

The script writes logs to `/tmp/cron_lwa.log`.

For a make-up run:

```bash
cd /home/peijin/ovro-lwa-dataportal
python3 dbscripts/generate_daily_movie.py --start 2026-05-14 --end 2026-05-17
```
