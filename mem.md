# OVRO-LWA Data Portal — agent memory

## Purpose
Single-page portal: preview spectrum/movies, query imaging HDFs by UTC range, stage a **zip** download with email (Cloudflare Turnstile). Production: `https://ovsa.njit.edu/lwa/`; API under `/portal/`.

## Layout
| Path | Role |
|------|------|
| `backend/` | FastAPI (`main.py`), routes `backend/routes/portal.py`, DB `backend/database.py`, paths `backend/files.py`, config `backend/config.py` |
| `frontend/` | Vite + React (`App.jsx`, `api.js`) |
| `dbscripts/` | Build/append SQLite from NAS (`build_db_fnames.py`, `append_dataset.py`) |
| `llm/` | Gemini AI daily summaries (`ai_summary.db`) |
| `website/` | Legacy Flask (reference only) |

## NAS roots (`backend/config.py`)
- `spectrum` → `/common/lwa/spec_v2` (daily/hourly PNG previews)
- `spectrum_fits` → `/nas8/lwa/spec_v2/fits` (one `.fits` per day: `yyyymmdd.fits`)
- `imaging` → `/nas7/ovro-lwa-data/hdf/slow`
- `movies` → `/common/webplots/lwa-data/qlook_daily/movies`

DB default: `dbscripts/lwa_data.db` (`LWA_DB_PATH`).

## SQLite tables (spectrum-relevant)
- `spec_daily`, `spec_hourly` — PNG paths (preview)
- `spec_daily_fits` — daily FITS paths
- `img_lev1_mfs`, `img_lev15_fch`, etc. — imaging HDFs
- `datacount` — per-day counts for calendar UI

## Data request flow
1. **POST /portal/query** — `query_imaging()` + optional `get_spec_fits_paths_for_range()` when `with_all_day_spectrum=true`. Limits: ≤400 files, &lt;3 GB → `stage_available`.
2. **POST /portal/stage** — copies imaging HDFs to `STAGE_WORK_PATH/{uuid}/`, optional spectrum FITS, `shutil.make_archive(..., "zip")` → `STAGE_READY_PATH/{uuid}.zip`, email via `send_stage_email`.
3. **GET /portal/download/{stage_id}.zip** — download bundle.

Path safety: `files.full_path_to_root_and_relative()`, `files.resolve_to_allowed_path()`; missing files skipped silently.

## Spectrum checkbox semantics
- UI label: “With all day spectrum”
- **Query** counts/packs **daily FITS** (`spec_daily_fits` / `get_spec_fits_paths_for_range`)
- **Preview** uses PNGs (`get_spectrum_paths_for_date` — daily + hourly)
- Staging must use same FITS helper as query (not PNG paths)

## Staging paths
- `STAGE_WORK_PATH`, `STAGE_READY_PATH` (env-overridable)
- Zip layout: imaging keeps DB-relative paths; spectrum FITS under `spectrum/{filename}.fits`
- Work dir removed after each successful stage; **ready zips persist** until cron cleanup
- `dbscripts/cron_cleanup_stage.sh` @ **00:00 UTC** daily — deletes ready `*.zip` and orphaned work entries older than **12 h** (`STAGE_RETENTION_HOURS`)

## Frontend notes
- `queryWithAllDaySpectrum` → `postQuery` / `postStage` with `with_all_day_spectrum`
- Vite dev proxies `/portal` → `:5001`

## Common pitfalls
- Query vs stage must use same spectrum product (FITS vs PNG)
- Stage limits should include FITS when checkbox set
- `file_count` in stage response/email may be imaging-only unless updated
