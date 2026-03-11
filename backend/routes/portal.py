"""Portal API routes under /portal/."""
import os
import shutil
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel

from backend import database, files
from backend.config import (
    SPEC_ROOT,
    MOVIES_ROOT,
    STAGE_WORK_PATH,
    STAGE_READY_PATH,
    TURNSTILE_SECRET_KEY,
    PORTAL_BASE_URL,
)
from backend.emailer import send_stage_email
from backend.visitors import get_visitor_count

SPEC_DAILY_PREFIX = f"{SPEC_ROOT}/daily/"
SPEC_HOURLY_PREFIX = f"{SPEC_ROOT}/hourly/"
MOVIES_PREFIX = f"{MOVIES_ROOT.rstrip('/')}/"

SPEC_DAILY_WEB = "https://ovsa.njit.edu/lwa-data/qlook_spec_v2/daily/"
SPEC_HOURLY_WEB = "https://ovsa.njit.edu/lwa-data/qlook_spec_v2/hourly/"
MOVIES_WEB = "https://ovsa.njit.edu/lwa-data/qlook_daily/movies/"


class QueryBody(BaseModel):
    start_time: str
    end_time: str
    data_type: str
    cadence: Optional[int] = None
    with_all_day_spectrum: bool = False


class StageBody(BaseModel):
    start_time: str
    end_time: str
    data_type: str
    cadence: Optional[int] = None
    with_all_day_spectrum: bool = False
    email: str = ""
    turnstile_token: str = ""


def _verify_turnstile(token: str, remote_ip: Optional[str]) -> bool:
    """
    Verify Cloudflare Turnstile token. Returns True on success, False otherwise.
    """
    if not TURNSTILE_SECRET_KEY:
        # If Turnstile is not configured, treat as failure rather than silently passing.
        print("[TURNSTILE] Secret key not configured")
        return False
    if not token:
        return False

    import json
    from urllib import parse, request as urlrequest

    data = parse.urlencode(
        {
            "secret": TURNSTILE_SECRET_KEY,
            "response": token,
            **({"remoteip": remote_ip} if remote_ip else {}),
        }
    ).encode()
    req = urlrequest.Request(
        "https://challenges.cloudflare.com/turnstile/v0/siteverify",
        data=data,
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        with urlrequest.urlopen(req, timeout=5) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        success = bool(payload.get("success"))
        if not success:
            print(f"[TURNSTILE] Verification failed: {payload}")
        return success
    except Exception as exc:  # pragma: no cover - network failure
        print(f"[TURNSTILE] Error verifying token: {exc}")
        return False

router = APIRouter(prefix="/portal", tags=["portal"])


def _dir_to_ref(full_path: str) -> Optional[dict]:
    """Convert full NAS path to { root, path } for client; None if not under allowed root."""
    pair = files.full_path_to_root_and_relative(full_path)
    if not pair:
        return None
    return {"root": pair[0], "path": pair[1]}  # path with forward slashes


def _preview_url_from_dir(full_path: str) -> Optional[str]:
    """Convert full NAS path to external HTTP URL for preview images/movies."""
    p = str(full_path)
    if p.startswith(SPEC_DAILY_PREFIX):
        rel = p[len(SPEC_DAILY_PREFIX) :]
        return SPEC_DAILY_WEB + rel
    if p.startswith(SPEC_HOURLY_PREFIX):
        rel = p[len(SPEC_HOURLY_PREFIX) :]
        return SPEC_HOURLY_WEB + rel
    if p.startswith(MOVIES_PREFIX):
        rel = p[len(MOVIES_PREFIX) :]
        return MOVIES_WEB + rel
    return None


@router.get("/avail-dates")
def avail_dates() -> List[str]:
    """Return list of dates that have data (from spec_daily)."""
    return database.get_avail_dates()


@router.get("/day-summary/{date}")
def day_summary(date: str) -> dict:
    """Return per-day product counts for badges (datacount row)."""
    dc = database.get_datacount_for_date(date)
    if not dc:
        # Return zeros if no entry exists for this date.
        return {
            "date": date,
            "n_spec_daily": 0,
            "n_spec_daily_fits": 0,
            "n_spec_hourly": 0,
            "n_img_lev1_mfs": 0,
            "n_img_lev1_fch": 0,
            "n_img_lev15_mfs": 0,
            "n_img_lev15_fch": 0,
            "n_movies": 0,
        }
    return dc


@router.get("/coverage/{year}")
def data_coverage(year: int) -> dict:
    """Return per-day datacount summaries for a given year."""
    if year < 1900 or year > 9999:
        raise HTTPException(status_code=400, detail="Invalid year")
    days = database.get_datacount_for_year(year)
    return {"year": year, "days": days}


@router.get("/visitors/count")
def visitors_count() -> dict:
    """Return total number of recorded visits."""
    return {"count": get_visitor_count()}


@router.get("/preview/spectrum/{date}")
def preview_spectrum(date: str) -> dict:
    """Return spectrum preview URLs (external HTTP) and file refs for date."""
    dirs = database.get_spectrum_paths_for_date(date)
    files_meta: List[dict] = []
    urls: List[str] = []
    for d in dirs:
        r = _dir_to_ref(d)
        if r:
            files_meta.append(r)
        u = _preview_url_from_dir(d)
        if u:
            urls.append(u)
    return {"date": date, "files": files_meta, "urls": urls}


@router.get("/preview/movie/{date}")
def preview_movie(date: str) -> dict:
    """Return single preview URL and file ref for movie on date, or null."""
    dir_path = database.get_movie_path_for_date(date)
    if not dir_path:
        return {"date": date, "file": None, "url": None}
    ref = _dir_to_ref(dir_path)
    url = _preview_url_from_dir(dir_path)
    return {"date": date, "file": ref, "url": url}


def _file_count_and_size(rows: List[tuple]) -> tuple:
    """Given list of (datetime, dir_path), return (count, total_bytes). dir_path is full NAS path to file."""
    total = 0
    count = 0
    for _dts, dir_path in rows:
        pair = files.full_path_to_root_and_relative(dir_path)
        if not pair:
            continue
        root_key, rel = pair
        p = files.resolve_to_allowed_path(root_key, rel)
        if p is None:
            continue
        try:
            if p.is_file():
                total += p.stat().st_size
                count += 1
        except OSError:
            pass
    return count, total


@router.post("/query")
def query_data(body: QueryBody) -> dict:
    """
    Query imaging table by start_time, end_time, data_type, optional cadence.
    Returns only aggregate information (file_count, total_size_bytes, stage_available)
    while keeping the per-file list on the backend for staging.
    """
    rows = database.query_imaging(
        start_time=body.start_time,
        end_time=body.end_time,
        data_type=body.data_type,
        cadence_seconds=body.cadence,
    )
    file_count, total_size_bytes = _file_count_and_size(rows)
    # If requested, include all-day spectrum FITS files in the count/size.
    if body.with_all_day_spectrum:
        start_date = body.start_time[:10]
        end_date = body.end_time[:10]
        fits_paths = database.get_spec_fits_paths_for_range(start_date, end_date)
        if fits_paths:
            fits_rows = [(None, p) for p in fits_paths]
            fits_count, fits_size = _file_count_and_size(fits_rows)
            file_count += fits_count
            total_size_bytes += fits_size
    STAGE_MAX_FILES = 400
    STAGE_MAX_BYTES = 3 * 1024**3  # 3 GB
    stage_available = file_count <= STAGE_MAX_FILES and total_size_bytes < STAGE_MAX_BYTES and file_count > 0
    return {
        "file_count": file_count,
        "total_size_bytes": total_size_bytes,
        "stage_available": stage_available,
        "start_time": body.start_time,
        "end_time": body.end_time,
    }


@router.post("/stage")
def stage_data(request: Request, background: BackgroundTasks, body: StageBody) -> dict:
    """Create a unique dir, copy query result files into it, zip, return download URL and send email."""
    # Verify Cloudflare Turnstile token
    remote_ip = request.client.host if request.client else None
    if not _verify_turnstile(getattr(body, "turnstile_token", ""), remote_ip):
        raise HTTPException(status_code=400, detail="Turnstile verification failed")
    if not body.email:
        raise HTTPException(status_code=400, detail="Email is required for staging")

    STAGE_MAX_FILES = 400
    STAGE_MAX_BYTES = 3 * 1024**3  # 3 GB
    rows = database.query_imaging(
        start_time=body.start_time,
        end_time=body.end_time,
        data_type=body.data_type,
        cadence_seconds=body.cadence,
    )
    if not rows:
        raise HTTPException(status_code=400, detail="No files in range")
    file_count, total_size_bytes = _file_count_and_size(rows)
    if file_count > STAGE_MAX_FILES:
        raise HTTPException(status_code=400, detail="Too many files in one request")
    if total_size_bytes >= STAGE_MAX_BYTES:
        raise HTTPException(status_code=400, detail="Total size >= 3GB, staging not available")

    stage_id = uuid.uuid4().hex
    work_dir = STAGE_WORK_PATH / stage_id
    ready_base = STAGE_READY_PATH / stage_id  # .zip will be appended by make_archive
    try:
        work_dir.mkdir(parents=True, exist_ok=True)
        # Copy imaging files
        for _dts, dir_path in rows:
            pair = files.full_path_to_root_and_relative(dir_path)
            if not pair:
                continue
            root_key, rel = pair
            src = files.resolve_to_allowed_path(root_key, rel)
            if src is None or not src.is_file():
                continue
            dest = work_dir / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
        # Optionally copy daily spectrum PNGs / FITS
        if body.with_all_day_spectrum:
            try:
                start_d = datetime.strptime(body.start_time[:10], "%Y-%m-%d").date()
                end_d = datetime.strptime(body.end_time[:10], "%Y-%m-%d").date()
            except ValueError:
                start_d = end_d = None
            if start_d is not None and end_d is not None:
                d = start_d
                while d <= end_d:
                    paths = database.get_spectrum_paths_for_date(d.strftime("%Y-%m-%d"))
                    for full_path in paths:
                        pair = files.full_path_to_root_and_relative(full_path)
                        if not pair:
                            continue
                        root_key, rel = pair
                        src = files.resolve_to_allowed_path(root_key, rel)
                        if src and src.is_file():
                            dest = work_dir / "spectrum" / rel
                            dest.parent.mkdir(parents=True, exist_ok=True)
                            shutil.copy2(src, dest)
                    d += timedelta(days=1)

        # Zip into ready directory
        STAGE_READY_PATH.mkdir(parents=True, exist_ok=True)
        shutil.make_archive(str(ready_base), "zip", work_dir)
        shutil.rmtree(work_dir, ignore_errors=True)

        download_path = f"/portal/download/{stage_id}.zip"
        download_url = f"{PORTAL_BASE_URL.rstrip('/')}{download_path}"
        # Send notification email in the background
        background.add_task(
            send_stage_email,
            body.email.strip(),
            download_url,
            file_count,
            total_size_bytes,
            body.start_time,
            body.end_time,
        )
        return {
            "stage_id": stage_id,
            "download_url": download_url,
            "file_count": file_count,
            "total_size_bytes": total_size_bytes,
            "email": body.email or None,
        }
    except OSError as e:
        if work_dir.exists():
            shutil.rmtree(work_dir, ignore_errors=True)
        raise HTTPException(status_code=500, detail=f"Staging failed: {e}")


@router.get("/files")
def serve_file(
    root: str = Query(..., description="Root key: spectrum, imaging, movies"),
    path: str = Query(..., description="Relative path under root"),
) -> FileResponse:
    """Stream file from NAS; path must be under allowed root. For images/video (inline)."""
    resolved = files.resolve_to_allowed_path(root, path)
    if not resolved or not resolved.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    headers = {"Content-Disposition": f'inline; filename="{resolved.name}"'}
    return FileResponse(str(resolved), media_type=None, headers=headers)


@router.get("/download")
def download_file(
    root: str = Query(..., description="Root key: spectrum, imaging, movies"),
    path: str = Query(..., description="Relative path under root"),
) -> FileResponse:
    """Stream file from NAS for download (attachment)."""
    resolved = files.resolve_to_allowed_path(root, path)
    if not resolved or not resolved.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    headers = {"Content-Disposition": f'attachment; filename="{resolved.name}"'}
    return FileResponse(str(resolved), media_type="application/octet-stream", headers=headers)


@router.get("/download/{stage_id}.zip")
def download_staged_zip(stage_id: str) -> FileResponse:
    """Download a staged zip bundle by UUID."""
    # Basic validation that this looks like a UUID hex string
    try:
        uuid.UUID(stage_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid stage id")

    zip_path = STAGE_READY_PATH / f"{stage_id}.zip"
    if not zip_path.is_file():
        raise HTTPException(status_code=404, detail="Staged zip not found")
    headers = {"Content-Disposition": f'attachment; filename="{stage_id}.zip"'}
    return FileResponse(str(zip_path), media_type="application/zip", headers=headers)


@router.get("/ephemeris")
def ephemeris() -> dict:
    """Return current UTC, sun alt/az, sunrise/sunset, 12° up/down (JSON)."""
    import ephem
    from datetime import datetime, timedelta
    import pytz

    ovro = ephem.Observer()
    ovro.lat = "37.2332"
    ovro.lon = "-118.2872"
    ovro.elevation = 1222
    current_utc = datetime.now(pytz.UTC)
    ovro.date = current_utc
    sun = ephem.Sun()
    sun.compute(ovro)
    alt_deg = float(sun.alt) * 180 / ephem.pi
    az_deg = float(sun.az) * 180 / ephem.pi
    next_sunrise = ovro.next_rising(sun).datetime()
    next_sunset = ovro.next_setting(sun).datetime()
    prev_sunrise = ovro.previous_rising(sun).datetime()
    sunrise_time = prev_sunrise if prev_sunrise.date() == current_utc.date() else next_sunrise
    sunset_time = next_sunset

    def find_altitude_crossing(observer, start_time, direction="rising", target_alt_deg=12.0):
        observer.date = start_time
        step = ephem.minute
        for _ in range(120):
            sun.compute(observer)
            alt = float(sun.alt) * 180 / ephem.pi
            if (direction == "rising" and alt >= target_alt_deg) or (
                direction == "setting" and alt <= target_alt_deg
            ):
                return observer.date.datetime()
            observer.date += step
        return None

    sun_12up = find_altitude_crossing(ovro, sunrise_time, direction="rising")
    sun_12down = find_altitude_crossing(ovro, sunset_time - timedelta(hours=2), direction="setting")
    return {
        "current_time_utc": current_utc.strftime("%Y-%m-%d %H:%M:%S"),
        "alt_deg": round(alt_deg, 1),
        "az_deg": round(az_deg, 1),
        "sunrise_utc": sunrise_time.strftime("%Y-%m-%d %H:%M:%S"),
        "sunset_utc": sunset_time.strftime("%Y-%m-%d %H:%M:%S"),
        "sun_12up_utc": sun_12up.strftime("%Y-%m-%d %H:%M:%S") if sun_12up else None,
        "sun_12down_utc": sun_12down.strftime("%Y-%m-%d %H:%M:%S") if sun_12down else None,
    }
