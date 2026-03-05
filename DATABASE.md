# LWA Data Portal — Database Documentation

This document describes the SQLite database used by the OVRO-LWA data portal: table schemas, column meanings, and how the database is built.

---

## Overview

The database catalogs **spectrum**, **imaging**, and **movies** on the NAS. It provides:

- **Spectrum**: daily and hourly spectrum image paths.
- **Imaging**: HDF image files by data level (`lev1`, `lev15`) and type (`fch`, `mfs`).
- **Movies**: daily synoptic MFS movie files (one MP4 per date).
- **datacount**: Per-date counts of files in each category (derived from the above tables).

Default database file: `lwa_data.db` (can be overridden with the `LWA_DB_PATH` environment variable).

---

## Building the Database

Run the build script from the project root:

```bash
python build_db_fnames.py
```

Or with a custom path:

```bash
LWA_DB_PATH=/path/to/lwa_data.db python build_db_fnames.py
```

The script **drops and recreates** all tables on each run. It scans the NAS paths below and populates the tables. If an imaging row would violate the UNIQUE constraint on `datetime`, the script skips the insert and prints both the pre-existing path and the conflicting path.

**Data source roots (on NAS):**

| Product   | Root path                              |
|----------|----------------------------------------|
| Spectrum | `/common/lwa/spec_v2`                  |
| Imaging  | `/nas8/lwa/hdf/slow`                   |
| Movies   | `/common/webplots/lwa-data/qlook_daily/movies` |

---

## Appending New Data

Use `append_dataset.py` to add records **without** rebuilding the whole database. It scans the same NAS directories and inserts only records with date ≥ a given starting date. Use this for incremental updates (e.g. after new data has been written to the NAS).

**Basic usage:**

```bash
python append_dataset.py --starting_date 20260101
```

Only records with **date ≥** `20260101` (interpreted as `YYYY-MM-DD`) are considered. The script inserts into all tables and then **refreshes `datacount`** for every date ≥ the starting date (recomputing counts from the tables).

**Arguments:**

| Argument           | Required | Description |
|--------------------|----------|-------------|
| `--starting_date`  | Yes      | Only process records with date ≥ this. Format: `yyyymmdd` (e.g. `20260101`). |
| `--verbose`        | No       | When a row is skipped because of a UNIQUE conflict, print the pre-existing `dir` and the to-be-inserted `dir`. |
| `--db`             | No       | Path to the SQLite database. Default: `LWA_DB_PATH` env or `lwa_data.db`. |

**Behavior:**

- **Unique constraints:** For tables with a UNIQUE key (`spec_daily` date, `movies` date, and all `img_*` datetime), if the insert would duplicate an existing row, the script **skips** that row (no error). Use `--verbose` to see which paths were skipped and what was already in the DB.
- **spec_hourly:** No UNIQUE in the schema; rows are always inserted (re-running append for the same date can produce duplicate `(date, dir)` rows).
- **datacount:** After appending, every date ≥ starting date is removed from `datacount`, then counts are recomputed from the other tables and re-inserted, so `datacount` stays consistent with the data tables.

**Examples:**

```bash
# Append everything from 2026-01-01 onward
python append_dataset.py --starting_date 20260101

# Same, and print skipped duplicates
python append_dataset.py --starting_date 20260101 --verbose

# Use a specific database file
python append_dataset.py --starting_date 20260101 --db /path/to/lwa_data.db
```

---

## Tables and Columns

### 1. `spec_daily`

One row per **daily** spectrum image.

| Column | Type   | Constraints | Description |
|--------|--------|-------------|-------------|
| `date` | TEXT   | PRIMARY KEY | Calendar date, `YYYY-MM-DD`. |
| `dir`  | TEXT   | NOT NULL    | Full path to the PNG file on the NAS. |

**File convention:**  
`/common/lwa/spec_v2/daily/yyyymmdd.png`

---

### 2. `spec_hourly`

One row per **hourly** spectrum image (multiple rows per day possible).

| Column | Type   | Constraints | Description |
|--------|--------|-------------|-------------|
| `date` | TEXT   | —           | Calendar date, `YYYY-MM-DD`. |
| `dir`  | TEXT   | NOT NULL    | Full path to the PNG file on the NAS. |

**File convention:**  
`/common/lwa/spec_v2/hourly/yyyymm/dd_&lt;idx&gt;.png`  
(e.g. `202307/22_10.png` → date `2023-07-22`).

---

### 3. `img_lev1_mfs`

Imaging files: level 1, MFS (multi-frequency synthesis).

| Column     | Type   | Constraints   | Description |
|------------|--------|---------------|-------------|
| `date`     | TEXT   | NOT NULL      | Calendar date, `YYYY-MM-DD`. |
| `datetime` | TEXT   | NOT NULL, UNIQUE | Timestamp of the file, `YYYY-MM-DD HH:MM:SS`. |
| `dir`      | TEXT   | NOT NULL      | Full path to the HDF file on the NAS. |

**File convention:**  
`/nas8/lwa/hdf/slow/lev1/yyyy/mm/dd/ovro-lwa.lev1_mfs_10s.yyyy-mm-ddTHHMMSSZ.image_I.hdf`

---

### 4. `img_lev15_mfs`

Imaging files: level 1.5, MFS.

| Column     | Type   | Constraints   | Description |
|------------|--------|---------------|-------------|
| `date`     | TEXT   | NOT NULL      | Calendar date, `YYYY-MM-DD`. |
| `datetime` | TEXT   | NOT NULL, UNIQUE | Timestamp of the file, `YYYY-MM-DD HH:MM:SS`. |
| `dir`      | TEXT   | NOT NULL      | Full path to the HDF file on the NAS. |

**File convention:**  
`/nas8/lwa/hdf/slow/lev15/yyyy/mm/dd/ovro-lwa.lev15_mfs_10s.yyyy-mm-ddTHHMMSSZ.image_I.hdf`

---

### 5. `img_lev1_fch`

Imaging files: level 1, FCH (frequency channel).

| Column     | Type   | Constraints   | Description |
|------------|--------|---------------|-------------|
| `date`     | TEXT   | NOT NULL      | Calendar date, `YYYY-MM-DD`. |
| `datetime` | TEXT   | NOT NULL, UNIQUE | Timestamp of the file, `YYYY-MM-DD HH:MM:SS`. |
| `dir`      | TEXT   | NOT NULL      | Full path to the HDF file on the NAS. |

**File convention:**  
`/nas8/lwa/hdf/slow/lev1/yyyy/mm/dd/ovro-lwa.lev1_fch_10s.yyyy-mm-ddTHHMMSSZ.image_I.hdf`

---

### 6. `img_lev15_fch`

Imaging files: level 1.5, FCH.

| Column     | Type   | Constraints   | Description |
|------------|--------|---------------|-------------|
| `date`     | TEXT   | NOT NULL      | Calendar date, `YYYY-MM-DD`. |
| `datetime` | TEXT   | NOT NULL, UNIQUE | Timestamp of the file, `YYYY-MM-DD HH:MM:SS`. |
| `dir`      | TEXT   | NOT NULL      | Full path to the HDF file on the NAS. |

**File convention:**  
`/nas8/lwa/hdf/slow/lev15/yyyy/mm/dd/ovro-lwa.lev15_fch_10s.yyyy-mm-ddTHHMMSSZ.image_I.hdf`

---

### 7. `movies`

One row per **daily** synoptic MFS movie (MP4). At most one movie per calendar date.

| Column | Type   | Constraints | Description |
|--------|--------|-------------|-------------|
| `date` | TEXT   | UNIQUE      | Calendar date, `YYYY-MM-DD`. |
| `dir`  | TEXT   | NOT NULL    | Full path to the MP4 file on the NAS. |

**File convention:**  
`/common/webplots/lwa-data/qlook_daily/movies/yyyy/ovro-lwa-352.synop_mfs_image_I_movie_yyyymmdd.mp4`

---

### 8. `datacount`

One row per calendar date with **counts** of files in each product type. All counts are derived from the tables above (not from a separate scan).

| Column           | Type    | Constraints | Description |
|------------------|---------|-------------|-------------|
| `date`           | TEXT    | PRIMARY KEY | Calendar date, `YYYY-MM-DD`. |
| `n_spec_daily`   | INTEGER | NOT NULL    | Number of rows in `spec_daily` for this date (0 or 1). |
| `n_spec_hourly`  | INTEGER | NOT NULL    | Number of rows in `spec_hourly` for this date. |
| `n_img_lev1_mfs` | INTEGER | NOT NULL    | Number of rows in `img_lev1_mfs` for this date. |
| `n_img_lev1_fch` | INTEGER | NOT NULL    | Number of rows in `img_lev1_fch` for this date. |
| `n_img_lev15_mfs`| INTEGER | NOT NULL    | Number of rows in `img_lev15_mfs` for this date. |
| `n_img_lev15_fch`| INTEGER | NOT NULL    | Number of rows in `img_lev15_fch` for this date. |
| `n_movies`       | INTEGER | NOT NULL    | Number of rows in `movies` for this date (0 or 1). |

A date appears in `datacount` if it has at least one file in any of the spectrum, imaging, or movies tables.

---

## Column Semantics Summary

- **`date`**: Always calendar date in ISO form `YYYY-MM-DD`.
- **`datetime`**: Used only in imaging tables; full timestamp `YYYY-MM-DD HH:MM:SS` parsed from the filename; must be unique per imaging table.
- **`dir`**: Full filesystem path on the NAS to the file (spectrum PNG, imaging HDF, or movie MP4). Use as-is for access on the NAS or for mapping to URLs in the portal.

---

## Example Queries

**All daily spectrum files for a date:**

```sql
SELECT dir FROM spec_daily WHERE date = '2024-01-15';
```

**Hourly spectrum paths for a date:**

```sql
SELECT dir FROM spec_hourly WHERE date = '2024-01-15' ORDER BY dir;
```

**Imaging files (lev1 FCH) for a date:**

```sql
SELECT datetime, dir FROM img_lev1_fch WHERE date = '2024-01-15' ORDER BY datetime;
```

**Movie for a date:**

```sql
SELECT dir FROM movies WHERE date = '2024-01-15';
```

**Dates that have at least one product:**

```sql
SELECT date, n_spec_daily, n_spec_hourly, n_img_lev1_mfs, n_img_lev1_fch, n_img_lev15_mfs, n_img_lev15_fch, n_movies
FROM datacount
ORDER BY date;
```

**Dates with no imaging data:**

```sql
SELECT date FROM datacount
WHERE n_img_lev1_mfs = 0 AND n_img_lev1_fch = 0 AND n_img_lev15_mfs = 0 AND n_img_lev15_fch = 0;
```

**Dates that have a movie:**

```sql
SELECT date FROM datacount WHERE n_movies > 0;
```
