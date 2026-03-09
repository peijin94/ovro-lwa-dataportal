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
