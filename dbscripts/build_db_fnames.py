import os
import sqlite3
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Tuple


# Root locations on NAS
SPEC_ROOT = "/common/lwa/spec_v2"
SPEC_DAILY_DIR = os.path.join(SPEC_ROOT, "daily")
SPEC_HOURLY_DIR = os.path.join(SPEC_ROOT, "hourly")

SPEC_FITS_ROOT = "/nas8/lwa/spec_v2/fits"

IMG_ROOT = "/nas7/ovro-lwa-data/hdf/slow"

MOVIES_ROOT = "/common/webplots/lwa-data/qlook_daily/movies"


@dataclass
class DataCounts:
    n_spec_daily: int = 0
    n_spec_daily_fits: int = 0
    n_spec_hourly: int = 0
    n_img_lev1_mfs: int = 0
    n_img_lev1_fch: int = 0
    n_img_lev15_mfs: int = 0
    n_img_lev15_fch: int = 0
    n_movies: int = 0


DateCounts = Dict[str, DataCounts]


def init_db(conn: sqlite3.Connection) -> None:
    cur = conn.cursor()

    # Drop and recreate all tables so the script always rebuilds from scratch
    cur.executescript(
        """
        DROP TABLE IF EXISTS spec_daily;
        DROP TABLE IF EXISTS spec_hourly;
        DROP TABLE IF EXISTS spec_daily_fits;
        DROP TABLE IF EXISTS img_lev1_mfs;
        DROP TABLE IF EXISTS img_lev15_mfs;
        DROP TABLE IF EXISTS img_lev1_fch;
        DROP TABLE IF EXISTS img_lev15_fch;
        DROP TABLE IF EXISTS movies;
        DROP TABLE IF EXISTS datacount;

        CREATE TABLE spec_daily (
            date TEXT PRIMARY KEY,
            dir  TEXT NOT NULL
        );

        CREATE TABLE spec_hourly (
            date TEXT NOT NULL,
            dir  TEXT NOT NULL
        );

        CREATE TABLE spec_daily_fits (
            date TEXT PRIMARY KEY,
            dir  TEXT NOT NULL
        );

        CREATE TABLE img_lev1_mfs (
            date     TEXT NOT NULL,
            datetime TEXT NOT NULL UNIQUE
        );

        CREATE TABLE img_lev15_mfs (
            date     TEXT NOT NULL,
            datetime TEXT NOT NULL UNIQUE
        );

        CREATE TABLE img_lev1_fch (
            date     TEXT NOT NULL,
            datetime TEXT NOT NULL UNIQUE
        );

        CREATE TABLE img_lev15_fch (
            date     TEXT NOT NULL,
            datetime TEXT NOT NULL UNIQUE
        );

        CREATE TABLE movies (
            date TEXT UNIQUE,
            dir  TEXT NOT NULL
        );

        CREATE TABLE datacount (
            date               TEXT PRIMARY KEY,
            n_spec_daily       INTEGER NOT NULL,
            n_spec_daily_fits  INTEGER NOT NULL,
            n_spec_hourly      INTEGER NOT NULL,
            n_img_lev1_mfs     INTEGER NOT NULL,
            n_img_lev1_fch     INTEGER NOT NULL,
            n_img_lev15_mfs    INTEGER NOT NULL,
            n_img_lev15_fch    INTEGER NOT NULL,
            n_movies           INTEGER NOT NULL
        );
        """
    )

    conn.commit()


def ensure_dir_exists(path: str, label: str) -> bool:
    if not os.path.isdir(path):
        print(f"[WARN] {label} directory does not exist: {path}")
        return False
    return True


def populate_spec_daily(conn: sqlite3.Connection, counts: DateCounts) -> None:
    if not ensure_dir_exists(SPEC_DAILY_DIR, "spec_daily"):
        return

    rows: List[Tuple[str, str]] = []

    for fname in sorted(os.listdir(SPEC_DAILY_DIR)):
        if not fname.endswith(".png"):
            continue
        stem = fname[:-4]
        if len(stem) != 8 or not stem.isdigit():
            continue

        yyyy, mm, dd = stem[0:4], stem[4:6], stem[6:8]
        date_str = f"{yyyy}-{mm}-{dd}"
        full_path = os.path.join(SPEC_DAILY_DIR, fname)

        rows.append((date_str, full_path))

        if date_str not in counts:
            counts[date_str] = DataCounts()
        counts[date_str].n_spec_daily += 1

    cur = conn.cursor()
    cur.executemany("INSERT INTO spec_daily (date, dir) VALUES (?, ?)", rows)


def populate_spec_hourly(conn: sqlite3.Connection, counts: DateCounts) -> None:
    if not ensure_dir_exists(SPEC_HOURLY_DIR, "spec_hourly"):
        return

    rows: List[Tuple[str, str]] = []

    for ym in sorted(os.listdir(SPEC_HOURLY_DIR)):
        ym_dir = os.path.join(SPEC_HOURLY_DIR, ym)
        if not os.path.isdir(ym_dir):
            continue
        if len(ym) != 6 or not ym.isdigit():
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
            full_path = os.path.join(ym_dir, fname)

            rows.append((date_str, full_path))

            if date_str not in counts:
                counts[date_str] = DataCounts()
            counts[date_str].n_spec_hourly += 1

    cur = conn.cursor()
    cur.executemany("INSERT INTO spec_hourly (date, dir) VALUES (?, ?)", rows)


def populate_spec_daily_fits(conn: sqlite3.Connection, counts: DateCounts) -> None:
    """Populate spec_daily_fits (per-day FITS) from SPEC_FITS_ROOT/yyyymmdd.fits."""
    if not ensure_dir_exists(SPEC_FITS_ROOT, "spec_daily_fits"):
        return

    rows: List[Tuple[str, str]] = []

    for fname in sorted(os.listdir(SPEC_FITS_ROOT)):
        if not fname.endswith(".fits"):
            continue
        stem = fname[:-5]  # strip .fits
        if len(stem) != 8 or not stem.isdigit():
            continue
        yyyy, mm, dd = stem[0:4], stem[4:6], stem[6:8]
        date_str = f"{yyyy}-{mm}-{dd}"
        full_path = os.path.join(SPEC_FITS_ROOT, fname)

        rows.append((date_str, full_path))

        if date_str not in counts:
            counts[date_str] = DataCounts()
        counts[date_str].n_spec_daily_fits += 1

    if not rows:
        return
    cur = conn.cursor()
    cur.executemany("INSERT INTO spec_daily_fits (date, dir) VALUES (?, ?)", rows)

def parse_image_datetime_from_fname(fname: str) -> Tuple[str, str]:
    """
    From a filename like:
    ovro-lwa.lev1_fch_10s.2024-01-01T161401Z.image_I.hdf
    extract date 'YYYY-MM-DD' and datetime 'YYYY-MM-DD HH:MM:SS'.
    """
    base = os.path.basename(fname)
    parts = base.split(".")
    if len(parts) < 5:
        raise ValueError(f"Unexpected filename format: {fname}")

    dt_part = parts[2]  # e.g. '2024-01-01T161401Z'
    if not dt_part.endswith("Z"):
        raise ValueError(f"Unexpected datetime format (no trailing Z): {fname}")

    dt_part = dt_part[:-1]  # remove trailing 'Z'
    dt = datetime.strptime(dt_part, "%Y-%m-%dT%H%M%S")
    date_str = dt.date().isoformat()
    datetime_str = dt.strftime("%Y-%m-%d %H:%M:%S")
    return date_str, datetime_str


def populate_img_table(
    conn: sqlite3.Connection,
    counts: DateCounts,
    level: str,
    kind: str,
    table_name: str,
    count_field: str,
) -> None:
    """
    level: 'lev1' or 'lev15'
    kind: 'mfs' or 'fch'
    table_name: one of img_lev1_mfs, img_lev15_mfs, img_lev1_fch, img_lev15_fch
    count_field: corresponding attribute name in DataCounts
    """
    level_dir = os.path.join(IMG_ROOT, level)
    if not ensure_dir_exists(level_dir, table_name):
        return

    pattern_fragment = f"{level}_{kind}_"
    rows: List[Tuple[str, str]] = []

    for yyyy in sorted(os.listdir(level_dir)):
        y_dir = os.path.join(level_dir, yyyy)
        if not os.path.isdir(y_dir) or len(yyyy) != 4 or not yyyy.isdigit():
            continue

        for mm in sorted(os.listdir(y_dir)):
            m_dir = os.path.join(y_dir, mm)
            if not os.path.isdir(m_dir) or len(mm) != 2 or not mm.isdigit():
                continue

            for dd in sorted(os.listdir(m_dir)):
                d_dir = os.path.join(m_dir, dd)
                if not os.path.isdir(d_dir) or len(dd) != 2 or not dd.isdigit():
                    continue

                for fname in sorted(os.listdir(d_dir)):
                    if not fname.endswith(".hdf"):
                        continue
                    if pattern_fragment not in fname:
                        continue

                    try:
                        date_str, datetime_str = parse_image_datetime_from_fname(fname)
                    except ValueError as e:
                        print(f"[WARN] {e}")
                        continue

                    rows.append((date_str, datetime_str))

                    if date_str not in counts:
                        counts[date_str] = DataCounts()
                    counter = counts[date_str]
                    setattr(counter, count_field, getattr(counter, count_field) + 1)

    cur = conn.cursor()
    for date_str, datetime_str in rows:
        try:
            cur.execute(
                f"INSERT INTO {table_name} (date, datetime) VALUES (?, ?)",
                (date_str, datetime_str),
            )
        except sqlite3.IntegrityError as e:
            if "UNIQUE" in str(e) or "unique" in str(e):
                print(
                    f"[CONFLICT] {table_name} datetime={datetime_str!r} (skipping duplicate)"
                )
            else:
                raise


def populate_movies(conn: sqlite3.Connection, counts: DateCounts) -> None:
    """
    Scan MOVIES_ROOT/yyyy/ for ovro-lwa-352.synop_mfs_image_I_movie_yyyymmdd.mp4
    and insert (date, dir). On UNIQUE date conflict, print pre-existing and new dir.
    """
    if not ensure_dir_exists(MOVIES_ROOT, "movies"):
        return

    cur = conn.cursor()
    prefix = "ovro-lwa-352.synop_mfs_image_I_movie_"

    for yyyy in sorted(os.listdir(MOVIES_ROOT)):
        y_dir = os.path.join(MOVIES_ROOT, yyyy)
        if not os.path.isdir(y_dir) or len(yyyy) != 4 or not yyyy.isdigit():
            continue

        for fname in sorted(os.listdir(y_dir)):
            if not fname.endswith(".mp4"):
                continue
            if prefix not in fname:
                continue
            stem = fname[:-4]
            idx = stem.find(prefix)
            if idx < 0:
                continue
            yyyymmdd = stem[idx + len(prefix) : idx + len(prefix) + 8]
            if len(yyyymmdd) != 8 or not yyyymmdd.isdigit():
                continue
            date_str = f"{yyyymmdd[0:4]}-{yyyymmdd[4:6]}-{yyyymmdd[6:8]}"
            full_path = os.path.join(y_dir, fname)

            if date_str not in counts:
                counts[date_str] = DataCounts()
            counts[date_str].n_movies += 1

            try:
                cur.execute(
                    "INSERT INTO movies (date, dir) VALUES (?, ?)",
                    (date_str, full_path),
                )
            except sqlite3.IntegrityError as e:
                if "UNIQUE" in str(e) or "unique" in str(e):
                    cur.execute("SELECT dir FROM movies WHERE date = ?", (date_str,))
                    row = cur.fetchone()
                    existing_dir = row[0] if row else "(unknown)"
                    print(
                        f"[CONFLICT] movies date={date_str!r}\n"
                        f"  pre-existing dir: {existing_dir}\n"
                        f"  to-be-inserted dir: {full_path}"
                    )
                else:
                    raise


def populate_datacount(conn: sqlite3.Connection, counts: DateCounts) -> None:
    cur = conn.cursor()

    rows = [
        (
            date,
            dc.n_spec_daily,
            dc.n_spec_daily_fits,
            dc.n_spec_hourly,
            dc.n_img_lev1_mfs,
            dc.n_img_lev1_fch,
            dc.n_img_lev15_mfs,
            dc.n_img_lev15_fch,
            dc.n_movies,
        )
        for date, dc in sorted(counts.items())
    ]

    cur.executemany(
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
        rows,
    )


def build_database(db_path: str = "lwa_data.db") -> None:
    print(f"[INFO] Building database at {db_path}")
    conn = sqlite3.connect(db_path)
    try:
        init_db(conn)

        counts: DateCounts = {}

        print("[INFO] Populating spec_daily")
        populate_spec_daily(conn, counts)

        print("[INFO] Populating spec_hourly")
        populate_spec_hourly(conn, counts)

        print("[INFO] Populating spec_daily_fits")
        populate_spec_daily_fits(conn, counts)

        print("[INFO] Populating img_lev1_mfs")
        populate_img_table(
            conn, counts, level="lev1", kind="mfs", table_name="img_lev1_mfs",
            count_field="n_img_lev1_mfs"
        )

        print("[INFO] Populating img_lev15_mfs")
        populate_img_table(
            conn, counts, level="lev15", kind="mfs", table_name="img_lev15_mfs",
            count_field="n_img_lev15_mfs"
        )

        print("[INFO] Populating img_lev1_fch")
        populate_img_table(
            conn, counts, level="lev1", kind="fch", table_name="img_lev1_fch",
            count_field="n_img_lev1_fch"
        )

        print("[INFO] Populating img_lev15_fch")
        populate_img_table(
            conn, counts, level="lev15", kind="fch", table_name="img_lev15_fch",
            count_field="n_img_lev15_fch"
        )

        print("[INFO] Populating movies")
        populate_movies(conn, counts)

        print("[INFO] Populating datacount")
        populate_datacount(conn, counts)

        conn.commit()
        print("[INFO] Done.")
    finally:
        conn.close()


if __name__ == "__main__":
    # Default DB in the repository root; change by setting LWA_DB_PATH env var.
    db_path_env = os.getenv("LWA_DB_PATH")
    path = db_path_env if db_path_env else "lwa_data.db"
    build_database(path)

