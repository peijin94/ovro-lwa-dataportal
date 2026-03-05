# OVRO LWA Data Portal

Single-page data portal for OVRO Long Wavelength Array: **preview** (daily/hourly spectrum, daily movie) and **data query + download**. Built with React + Tailwind (frontend) and FastAPI (backend), backed by SQLite ([DATABASE.md](DATABASE.md)).

The service is intended to run at **localhost:5001** and be exposed at **https://ovsa.njit.edu/lwa/**; all API routes live under **/portal/**.

---

## Quick start

### Backend

1. **Python 3.10+** and a built SQLite database (see [DATABASE.md](DATABASE.md) and `dbscripts/build_db_fnames.py`).
2. From the project root:
   ```bash
   pip install -r backend/requirements.txt
   export LWA_DB_PATH=/path/to/lwa_data.db   # optional; default: ./lwa_data.db
   python -m uvicorn backend.main:app --host 127.0.0.1 --port 5001
   ```
3. API: `http://localhost:5001/portal/avail-dates`, etc.

### Frontend (development)

1. From the project root:
   ```bash
   cd frontend
   npm install
   npm run dev
   ```
2. Vite runs at `http://localhost:5173` and proxies `/portal` to `http://localhost:5001`, so the app talks to the backend without CORS issues.
3. Ensure the backend is running on 5001.

### Production (single server)

1. Build the frontend:
   ```bash
   cd frontend && npm run build
   ```
2. Run the backend from the project root; it will serve the built frontend from `frontend/dist` at `/` and the API at `/portal/*`:
   ```bash
   python -m uvicorn backend.main:app --host 127.0.0.1 --port 5001
   ```
3. Point the reverse proxy (e.g. at ovsa.njit.edu) at `http://localhost:5001` under the path `/lwa/`.

---

## Configuration

| Variable | Where | Description |
|----------|-------|-------------|
| `LWA_DB_PATH` | Backend | Path to SQLite DB (default: `./lwa_data.db`). |
| `VITE_API_BASE` | Frontend | Backend base URL when not using the Vite proxy (e.g. `https://ovsa.njit.edu/lwa` in production). |
| `TURNSTILE_SITE_KEY` | Frontend/Backend | Cloudflare Turnstile site key (frontend reads via `import.meta.env.VITE_TURNSTILE_SITE_KEY`, backend uses secret key for verification). |
| `TURNSTILE_SECRET_KEY` | Backend | Cloudflare Turnstile secret key for verifying staging requests. |
| `SMTP_HOST` | Backend | SMTP host for staging notification emails (e.g. `smtp.gmail.com`). |
| `SMTP_PORT` | Backend | SMTP port (default `587`). |
| `SMTP_USER` | Backend | SMTP username (default `ovsa.operations.noreply@gmail.com`). |
| `SMTP_PASSWORD` | Backend | SMTP password or app-specific token. |
| `SMTP_FROM` | Backend | From address for staging emails (default `ovsa.operations.noreply@gmail.com`). |
| `STAGE_WORK_PATH` | Backend | Directory for temporary staging work trees (default `/home/peijin/tmpdir/work`). |
| `STAGE_READY_PATH` | Backend | Directory where ready zip files are written (default `/home/peijin/tmpdir/ready`). |

NAS roots (spectrum, imaging, movies, FITS) are set in `backend/config.py` to match `dbscripts/build_db_fnames.py`.

---

## Project layout

- **backend/** — FastAPI app: `/portal/*` routes, SQLite helpers, file serving from NAS.
- **frontend/** — Vite + React + Tailwind SPA: preview section, data query form, ephemeris.
- **website/** — Legacy Flask app (reference only).
- **dbscripts/** — Scripts to build/append the SQLite database; see [DATABASE.md](DATABASE.md).

---

## Portal API (summary)

- `GET /portal/avail-dates` — Dates with data.
- `GET /portal/preview/spectrum/{date}` — Spectrum file refs (root + path) for a date.
- `GET /portal/preview/movie/{date}` — Movie file ref (if any) for a date.
- `GET /portal/files?root=...&path=...` — Stream file (inline).
- `GET /portal/download?root=...&path=...` — Stream file (attachment).
- `GET /portal/download/{stage_id}.zip` — Download a staged zip bundle created by the portal (no directory listing).
- `POST /portal/query` — Body: `start_time`, `end_time`, `data_type`, `cadence`, `with_all_day_spectrum`; returns aggregate counts and size.
  - When `with_all_day_spectrum=true`, spectrum FITS files are included in the count/size.
- `GET /portal/ephemeris` — Sun position and rise/set times (JSON).

Full API and database schema: [DATABASE.md](DATABASE.md).
