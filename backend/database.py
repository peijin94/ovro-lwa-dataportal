"""SQLite helpers for portal; reads from lwa_data.db (see DATABASE.md)."""
import os
import sqlite3
from datetime import datetime as dt
from pathlib import Path
from typing import List, Optional, Tuple

from backend.config import LWA_DB_PATH, DATA_TYPE_TO_TABLE, IMG_ROOT


def get_connection() -> sqlite3.Connection:
    return sqlite3.connect(LWA_DB_PATH)


def get_avail_dates() -> List[str]:
    """Return sorted list of dates that have data (from spec_daily)."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT date FROM spec_daily ORDER BY date")
        return [row[0] for row in cur.fetchall()]
    finally:
        conn.close()


def get_spectrum_paths_for_date(date: str) -> List[str]:
    """Return list of full dir paths: one from spec_daily (if any) plus all from spec_hourly for date."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        paths = []
        cur.execute("SELECT dir FROM spec_daily WHERE date = ?", (date,))
        row = cur.fetchone()
        if row:
            paths.append(row[0])
        cur.execute("SELECT dir FROM spec_hourly WHERE date = ? ORDER BY dir", (date,))
        paths.extend(r[0] for r in cur.fetchall())
        return paths
    finally:
        conn.close()


def get_movie_path_for_date(date: str) -> Optional[str]:
    """Return single dir path for movie on date, or None.

    If the movies table does not exist (older DB), return None instead of raising.
    """
    conn = get_connection()
    try:
        cur = conn.cursor()
        try:
            cur.execute("SELECT dir FROM movies WHERE date = ?", (date,))
        except sqlite3.OperationalError as exc:
            # Handle legacy DBs without the movies table gracefully.
            if "no such table: movies" in str(exc):
                return None
            raise
        row = cur.fetchone()
        return row[0] if row else None
    finally:
        conn.close()


def get_spec_fits_paths_for_range(start_date: str, end_date: str) -> List[str]:
    """Return list of full FITS paths for dates in [start_date, end_date] from spec_daily_fits."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT dir FROM spec_daily_fits WHERE date >= ? AND date <= ? ORDER BY date",
            (start_date, end_date),
        )
        return [row[0] for row in cur.fetchall()]
    finally:
        conn.close()


def get_datacount_for_date(date: str) -> Optional[dict]:
    """Return datacount summary for a date, or None."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT
                date,
                n_spec_daily,
                n_spec_daily_fits,
                n_spec_hourly,
                n_img_lev1_mfs,
                n_img_lev1_fch,
                n_img_lev15_mfs,
                n_img_lev15_fch,
                n_movies
            FROM datacount
            WHERE date = ?
            """,
            (date,),
        )
        row = cur.fetchone()
        if not row:
            return None
        return {
            "date": row[0],
            "n_spec_daily": row[1],
            "n_spec_daily_fits": row[2],
            "n_spec_hourly": row[3],
            "n_img_lev1_mfs": row[4],
            "n_img_lev1_fch": row[5],
            "n_img_lev15_mfs": row[6],
            "n_img_lev15_fch": row[7],
            "n_movies": row[8],
        }
    finally:
        conn.close()


def query_imaging(
    start_time: str,
    end_time: str,
    data_type: str,
    cadence_seconds: Optional[int] = None,
) -> List[Tuple[str, str]]:
    """
    Return list of (datetime, full_path) for the given data_type
    (lev1_mfs, lev15_fch, etc.) with datetime in [start_time, end_time].
    Times are 'YYYY-MM-DD HH:MM:SS'. If cadence_seconds is given and >= 10,
    thin to at most one row per cadence_seconds (by datetime).
    """

    def datetime_to_full_path(prefix_dir: str, datetimes: List[str], dtype: str) -> List[str]:
        """Map imaging datetime strings to full NAS paths using naming convention."""
        paths: List[str] = []
        if dtype in ("lev1_mfs", "lev1_fch"):
            level = "lev1"
        elif dtype in ("lev15_mfs", "lev15_fch"):
            level = "lev15"
        else:
            level = "lev1"
        kind = "mfs" if "mfs" in dtype else "fch"

        for dts in datetimes:
            try:
                t = dt.strptime(dts, "%Y-%m-%d %H:%M:%S")
            except ValueError:
                # If the datetime format is unexpected, skip path reconstruction for this entry.
                continue
            yyyy = f"{t.year:04d}"
            mm = f"{t.month:02d}"
            dd = f"{t.day:02d}"
            hh = f"{t.hour:02d}"
            mi = f"{t.minute:02d}"
            ss = f"{t.second:02d}"
            subdir = os.path.join(level, yyyy, mm, dd)
            # Match existing file naming convention documented in DATABASE.md
            fname = f"ovro-lwa-352.{level}_{kind}_10s.{yyyy}-{mm}-{dd}T{hh}{mi}{ss}Z.image_I.hdf"
            paths.append(os.path.join(prefix_dir, subdir, fname))
        return paths

    table = DATA_TYPE_TO_TABLE.get(data_type)
    if not table:
        return []
    conn = get_connection()
    try:
        cur = conn.cursor()
        # Imaging tables store only (date, datetime); reconstruct full paths from datetime.
        cur.execute(
            f"SELECT datetime FROM {table} WHERE datetime >= ? AND datetime <= ? ORDER BY datetime",
            (start_time, end_time),
        )
        dts_list = [row[0] for row in cur.fetchall()]
        if not dts_list:
            return []
        paths = datetime_to_full_path(IMG_ROOT, dts_list, data_type)
        rows: List[Tuple[str, str]] = list(zip(dts_list, paths))
        # Cadence: if < 10s take all; if >= 10s thin by cadence
        if not cadence_seconds or cadence_seconds < 10:
            return rows
        result: List[Tuple[str, str]] = []
        last_ts: Optional[float] = None
        for dts, dir_path in rows:
            try:
                t = dt.strptime(dts, "%Y-%m-%d %H:%M:%S")
                ts = t.timestamp()
                if last_ts is None or (ts - last_ts) >= cadence_seconds:
                    result.append((dts, dir_path))
                    last_ts = ts
            except ValueError:
                result.append((dts, dir_path))
        return result
    finally:
        conn.close()