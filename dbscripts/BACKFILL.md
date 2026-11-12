# Manifest-scoped backlog publication

Do not rebuild the production database with `build_db_fnames.py`: that script drops tables. Back up the live SQLite database with the SQLite backup API before an explicit backfill.

## Inputs

`backfill_movies.py` consumes a summary `{ "days": { "YYYY-MM-DD": { "manifest_sha256": "..." } } }` and one `YYYY-MM-DD.json` per day. Each day manifest contains `date`, `status` (`complete`, `published_with_gaps`, or `event_sync`), `source_manifest_sha256`, and `frames` with exact `path`, `sha256`, and `observed` UTC timestamps. Preserve original filenames. Deduplicate aliases only when both timestamp and content hash agree.

The default movie policy is `utc_day`. Set `day_policy` explicitly to `web_day_through_next_03utc` for historical observing-day folders that retain the next UTC morning. That policy accepts timestamps from the named date at 00:00 up to (but not including) the next date at 03:00. It does not fabricate frames or change timestamps; the selected web-day folder must still match the manifest date.

`backfill_index.py` consumes a plan `{ "source_manifest_sha256": "...", "days": { "YYYY-MM-DD": { "status": "...", "provenance": {}, "input_manifest_sha256": "..." } } }`. Bind each input hash to the corresponding movie manifest. Optional `excluded_empty_hdf` lists only explicitly audited zero-byte HDF files; the indexer rechecks their location and zero size. No source is removed. Duplicate HDF timestamps are resolved only to the previously selected public path, with aliases recorded; new ambiguous timestamps fail closed.

## Execution

```bash
# Read-only is the default. Each report must be a NEW path (exclusive creation).
python dbscripts/backfill_index.py --plan plan.json --db /absolute/lwa_data.db \
  --movies-root /common/webplots/lwa-data/qlook_daily/movies/RELEASE \
  --mode images --report images-dry-run.jsonl

# After checking the report and taking a DB backup, add --apply with a new report.
# Only approved dates are reconciled; unrelated dates and all source files stay intact.
python dbscripts/backfill_index.py --plan plan.json --db /absolute/lwa_data.db \
  --movies-root /common/webplots/lwa-data/qlook_daily/movies/RELEASE \
  --mode images --report images-applied.jsonl --apply

# Run with systemd supervision and bounded CPU/memory, not an interactive tmux.
python dbscripts/backfill_movies.py --summary frames-summary.json --frames-dir frames \
  --work work --source-root /common/webplots/lwa-data/qlook_images/slow/synop \
  --movies-root /common/webplots/lwa-data/qlook_daily/movies/RELEASE --jobs 2 --threads 2

# Only validated movies with matching publication receipts can enter the index.
python dbscripts/backfill_index.py --plan plan.json --db /absolute/lwa_data.db \
  --movies-root /common/webplots/lwa-data/qlook_daily/movies/RELEASE \
  --mode movies --report movies-applied.jsonl --apply
```

Use `--days YYYY-MM-DD,...` for a pilot. Movie runs resume only when the current manifest and movie hash match the publication receipt. The work directory contains status, receipts and errors; an exit code of 1 requires investigation, not a success announcement. Versioned movie directories preserve old URLs/owners' files, while the `movies.dir` field points the portal to the new release.

## Database and caller compatibility

The backfill adds nullable `dir` fields to imaging tables, date indexes, and `portal_backfill_days` provenance. Existing append jobs may still create rows with NULL `dir`; the backend retains its previous filename reconstruction for those rows. Backfilled rows use their actual filenames, including historical `ovro-lwa` prefixes. Available dates include any indexed product, not just spectra.

## Acceptance checks

Run `python -m unittest discover -s tests -v` (ffmpeg/ffprobe required) and build the frontend. Check SQLite integrity and every selected date's counts/paths after applying. Verify `/portal/avail-dates`, `/portal/coverage/{year}`, `/portal/preview/movie/{date}`, bounded `/portal/query` requests, and public movie range GETs. Explicitly retain failed/held-date accounting; successful pilots are not proof that the entire batch completed.
