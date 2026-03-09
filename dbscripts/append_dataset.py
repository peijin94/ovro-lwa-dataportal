#!/usr/bin/env python3
"""
Append new records to the LWA database by scanning the same NAS directories.
Only records with date >= --starting_date are considered.
Duplicate unique keys are skipped; use --verbose to print those.

Directory traversal is optimized: only year/month/day (or year/month) folders
>= starting_date are entered, instead of listing all then filtering by date.
"""
import argparse
import os
import sqlite3
from datetime import datetime, timezone, timedelta

from build_db_fnames import (
    IMG_ROOT,
    MOVIES_ROOT,
    SPEC_DAILY_DIR,
    SPEC_HOURLY_DIR,
    SPEC_FITS_ROOT,
    DataCounts,
    ensure_dir_exists,
    parse_image_datetime_from_fname,
)


def _start_date_iso(starting_date: str) -> str:
    """Convert yyyymmdd to YYYY-MM-DD."""
    s = starting_date.strip()
    if len(s) != 8 or not s.isdigit():
        raise ValueError(f"starting_date must be yyyymmdd (8 digits), got {starting_date!r}")
    return f"{s[0:4]}-{s[4:6]}-{s[6:8]}"


def _start_ymd(start_date_iso: str) -> tuple:
    """Return (year, month, day) as ints from YYYY-MM-DD for folder pruning."""
    parts = start_date_iso.split("-")
    if len(parts) != 3:
        raise ValueError(f"start_date_iso must be YYYY-MM-DD, got {start_date_iso!r}")
    return (int(parts[0]), int(parts[1]), int(parts[2]))


def _append_spec_daily(
    conn: sqlite3.Connection,
    start_date_iso: str,
    verbose: bool,
) -> None:
    if not ensure_dir_exists(SPEC_DAILY_DIR, "spec_daily"):
        return
    cur = conn.cursor()
    for fname in sorted(os.listdir(SPEC_DAILY_DIR)):
        if not fname.endswith(".png"):
            continue
        stem = fname[:-4]
        if len(stem) != 8 or not stem.isdigit():
            continue
        yyyy, mm, dd = stem[0:4], stem[4:6], stem[6:8]
        date_str = f"{yyyy}-{mm}-{dd}"
        if date_str < start_date_iso:
            continue
        full_path = os.path.join(SPEC_DAILY_DIR, fname)
        try:
            cur.execute("INSERT INTO spec_daily (date, dir) VALUES (?, ?)", (date_str, full_path))
        except sqlite3.IntegrityError as e:
            if "UNIQUE" in str(e) or "unique" in str(e):
                if verbose:
                    cur.execute("SELECT dir FROM spec_daily WHERE date = ?", (date_str,))
                    row = cur.fetchone()
                    existing = row[0] if row else "(unknown)"
                    print(
                        f"[DUPLICATE] spec_daily date={date_str!r}\n"
                        f"  pre-existing dir: {existing}\n"
                        f"  to-be-inserted dir: {full_path}"
                    )
            else:
                raise


def _append_spec_hourly(
    conn: sqlite3.Connection,
    start_date_iso: str,
    start_ym: tuple,
) -> None:
    """Only enter YYYYMM folders where (year, month) >= start_ym."""
    if not ensure_dir_exists(SPEC_HOURLY_DIR, "spec_hourly"):
        return
    start_year, start_month = start_ym[0], start_ym[1]
    cur = conn.cursor()
    for ym in sorted(os.listdir(SPEC_HOURLY_DIR)):
        if len(ym) != 6 or not ym.isdigit():
            continue
        yyyy_i, mm_i = int(ym[0:4]), int(ym[4:6])
        if (yyyy_i, mm_i) < (start_year, start_month):
            continue
        ym_dir = os.path.join(SPEC_HOURLY_DIR, ym)
        if not os.path.isdir(ym_dir):
            continue
        yyyy, mm = ym[0:4], ym[4:6]
        for fname in sorted(os.listdir(ym_dir)):
            if not fname.endswith(".png"):
                continue
            stem = fname[:-4]
            if "_" not in stem:
                continue
            dd_part, _ = stem.split("_", 1)
            if len(dd_part) != 2 or not dd_part.isdigit():
                continue
            date_str = f"{yyyy}-{mm}-{dd_part}"
            if date_str < start_date_iso:
                continue
            full_path = os.path.join(ym_dir, fname)
            cur.execute("INSERT INTO spec_hourly (date, dir) VALUES (?, ?)", (date_str, full_path))


def _append_spec_daily_fits(
    conn: sqlite3.Connection,
    start_date_iso: str,
    verbose: bool,
) -> None:
    """Append spec_daily_fits entries under SPEC_FITS_ROOT."""
    if not ensure_dir_exists(SPEC_FITS_ROOT, "spec_daily_fits"):
        return
    cur = conn.cursor()
    for fname in sorted(os.listdir(SPEC_FITS_ROOT)):
        if not fname.endswith(".fits"):
            continue
        stem = fname[:-5]
        if len(stem) != 8 or not stem.isdigit():
            continue
        yyyy, mm, dd = stem[0:4], stem[4:6], stem[6:8]
        date_str = f"{yyyy}-{mm}-{dd}"
        if date_str < start_date_iso:
            continue
        full_path = os.path.join(SPEC_FITS_ROOT, fname)
        try:
            cur.execute("INSERT INTO spec_daily_fits (date, dir) VALUES (?, ?)", (date_str, full_path))
        except sqlite3.IntegrityError as e:
            if "UNIQUE" in str(e) or "unique" in str(e):
                if verbose:
                    cur.execute("SELECT dir FROM spec_daily_fits WHERE date = ?", (date_str,))
                    row = cur.fetchone()
                    existing = row[0] if row else "(unknown)"
                    print(
                        f"[DUPLICATE] spec_daily_fits date={date_str!r}\n"
                        f"  pre-existing dir: {existing}\n"
                        f"  to-be-inserted dir: {full_path}"
                    )
            else:
                raise


def _append_img_table(
    conn: sqlite3.Connection,
    start_date_iso: str,
    start_ymd: tuple,
    level: str,
    kind: str,
    table_name: str,
    verbose: bool,
) -> None:
    """Only enter year/month/day folders where (y, m, d) >= start_ymd."""
    level_dir = os.path.join(IMG_ROOT, level)
    if not ensure_dir_exists(level_dir, table_name):
        return
    start_year, start_month, start_day = start_ymd[0], start_ymd[1], start_ymd[2]
    pattern_fragment = f"{level}_{kind}_"
    cur = conn.cursor()
    for yyyy in sorted(os.listdir(level_dir)):
        if len(yyyy) != 4 or not yyyy.isdigit():
            continue
        if int(yyyy) < start_year:
            continue
        y_dir = os.path.join(level_dir, yyyy)
        if not os.path.isdir(y_dir):
            continue
        for mm in sorted(os.listdir(y_dir)):
            if len(mm) != 2 or not mm.isdigit():
                continue
            if (int(yyyy), int(mm)) < (start_year, start_month):
                continue
            m_dir = os.path.join(y_dir, mm)
            if not os.path.isdir(m_dir):
                continue
            for dd in sorted(os.listdir(m_dir)):
                if len(dd) != 2 or not dd.isdigit():
                    continue
                if (int(yyyy), int(mm), int(dd)) < (start_year, start_month, start_day):
                    continue
                d_dir = os.path.join(m_dir, dd)
                if not os.path.isdir(d_dir):
                    continue
                for fname in sorted(os.listdir(d_dir)):
                    if not fname.endswith(".hdf") or pattern_fragment not in fname:
                        continue
                    try:
                        date_str, datetime_str = parse_image_datetime_from_fname(fname)
                    except ValueError:
                        continue
                    if date_str < start_date_iso:
                        continue
                    try:
                        cur.execute(
                            f"INSERT INTO {table_name} (date, datetime) VALUES (?, ?)",
                            (date_str, datetime_str),
                        )
                    except sqlite3.IntegrityError as e:
                        if "UNIQUE" in str(e) or "unique" in str(e):
                            if verbose:
                                print(
                                    f"[DUPLICATE] {table_name} datetime={datetime_str!r} (skipping duplicate)"
                                )
                        else:
                            raise


def _append_movies(
    conn: sqlite3.Connection,
    start_date_iso: str,
    start_ymd: tuple,
    verbose: bool,
) -> None:
    """Only enter year folders where year >= start_ymd[0]."""
    if not ensure_dir_exists(MOVIES_ROOT, "movies"):
        return
    start_year = start_ymd[0]
    cur = conn.cursor()
    prefix = "ovro-lwa-352.synop_mfs_image_I_movie_"
    for yyyy in sorted(os.listdir(MOVIES_ROOT)):
        if len(yyyy) != 4 or not yyyy.isdigit():
            continue
        if int(yyyy) < start_year:
            continue
        y_dir = os.path.join(MOVIES_ROOT, yyyy)
        if not os.path.isdir(y_dir):
            continue
        for fname in sorted(os.listdir(y_dir)):
            if not fname.endswith(".mp4") or prefix not in fname:
                continue
            stem = fname[:-4]
            idx = stem.find(prefix)
            if idx < 0:
                continue
            yyyymmdd = stem[idx + len(prefix) : idx + len(prefix) + 8]
            if len(yyyymmdd) != 8 or not yyyymmdd.isdigit():
                continue
            date_str = f"{yyyymmdd[0:4]}-{yyyymmdd[4:6]}-{yyyymmdd[6:8]}"
            if date_str < start_date_iso:
                continue
            full_path = os.path.join(y_dir, fname)
            try:
                cur.execute("INSERT INTO movies (date, dir) VALUES (?, ?)", (date_str, full_path))
            except sqlite3.IntegrityError as e:
                if "UNIQUE" in str(e) or "unique" in str(e):
                    if verbose:
                        cur.execute("SELECT dir FROM movies WHERE date = ?", (date_str,))
                        row = cur.fetchone()
                        existing = row[0] if row else "(unknown)"
                        print(
                            f"[DUPLICATE] movies date={date_str!r}\n"
                            f"  pre-existing dir: {existing}\n"
                            f"  to-be-inserted dir: {full_path}"
                        )
                else:
                    raise


def _refresh_datacount(conn: sqlite3.Connection, start_date_iso: str) -> None:
    """Recompute datacount for all dates >= start_date_iso from current table contents."""
    cur = conn.cursor()
    cur.execute("DELETE FROM datacount WHERE date >= ?", (start_date_iso,))
    tables = [
        "spec_daily",
        "spec_daily_fits",
        "spec_hourly",
        "img_lev1_mfs",
        "img_lev1_fch",
        "img_lev15_mfs",
        "img_lev15_fch",
        "movies",
    ]
    count_cols = [
        "n_spec_daily",
        "n_spec_daily_fits",
        "n_spec_hourly",
        "n_img_lev1_mfs",
        "n_img_lev1_fch",
        "n_img_lev15_mfs",
        "n_img_lev15_fch",
        "n_movies",
    ]
    dates = set()
    for t in tables:
        cur.execute("SELECT DISTINCT date FROM " + t + " WHERE date >= ?", (start_date_iso,))
        dates.update(r[0] for r in cur.fetchall())
    for date in sorted(dates):
        row = [date]
        for t, col in zip(tables, count_cols):
            cur.execute("SELECT COUNT(*) FROM " + t + " WHERE date = ?", (date,))
            row.append(cur.fetchone()[0])
        cur.execute(
            """
            INSERT INTO datacount (
                date,
                n_spec_daily,
                n_spec_daily_fits,
                n_spec_hourly,
                n_img_lev1_mfs,
                n_img_lev1_fch,
                n_img_lev15_mfs,
                n_img_lev15_fch,
                n_movies
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            row,
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Append records to the LWA database from NAS directories (date >= starting_date)."
    )
    parser.add_argument(
        "--starting_date",
        default=None,
        metavar="yyyymmdd",
        help="Only insert records with date >= this (e.g. 20260101). Default: today - 3 days (UTC).",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print duplicate (skipped) records: pre-existing dir and to-be-inserted dir.",
    )
    parser.add_argument(
        "--db",
        default=os.getenv("LWA_DB_PATH", "lwa_data.db"),
        help="Path to SQLite database (default: LWA_DB_PATH or lwa_data.db).",
    )
    args = parser.parse_args()

    if args.starting_date is None:
        today = datetime.now(timezone.utc).date()
        start_d = today - timedelta(days=3)
        args.starting_date = start_d.strftime("%Y%m%d")

    start_date_iso = _start_date_iso(args.starting_date)
    start_ymd = _start_ymd(start_date_iso)
    start_ym = (start_ymd[0], start_ymd[1])

    conn = sqlite3.connect(args.db)
    try:
        print(f"[INFO] Appending from date >= {start_date_iso} into {args.db}")
        _append_spec_daily(conn, start_date_iso, args.verbose)
        _append_spec_hourly(conn, start_date_iso, start_ym)
        _append_spec_daily_fits(conn, start_date_iso, args.verbose)
        _append_img_table(
            conn, start_date_iso, start_ymd, "lev1", "mfs", "img_lev1_mfs", args.verbose
        )
        _append_img_table(
            conn, start_date_iso, start_ymd, "lev15", "mfs", "img_lev15_mfs", args.verbose
        )
        _append_img_table(
            conn, start_date_iso, start_ymd, "lev1", "fch", "img_lev1_fch", args.verbose
        )
        _append_img_table(
            conn, start_date_iso, start_ymd, "lev15", "fch", "img_lev15_fch", args.verbose
        )
        _append_movies(conn, start_date_iso, start_ymd, args.verbose)
        _refresh_datacount(conn, start_date_iso)
        conn.commit()
        print("[INFO] Done.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
