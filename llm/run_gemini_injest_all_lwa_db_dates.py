#!/usr/bin/env python3
"""
For every distinct calendar date key in lwa_data.db, run Gemini on that day's hourly
spectrogram PNGs and upsert the markdown summary into ai_summary.db.

Dates are processed in reverse chronological order (newest first).

Uses the same ingest path as llm/run_gemini_injest_db.py.

Usage:
  export GEMINI_API_KEY=...
  python llm/run_gemini_injest_all_lwa_db_dates.py
  python llm/run_gemini_injest_all_lwa_db_dates.py --dry-run
  python llm/run_gemini_injest_all_lwa_db_dates.py --limit 3
  python llm/run_gemini_injest_all_lwa_db_dates.py --skip-existing

Stdout is mirrored to run.log (default: llm/run.log). Problem dates are appended to run.err
(default: llm/run.err) with columns: UTC timestamp, YYYY-MM-DD, reason.
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import IO, TextIO

# Import sibling module when run as: python llm/run_gemini_injest_all_lwa_db_dates.py
_LLM_DIR = Path(__file__).resolve().parent
if str(_LLM_DIR) not in sys.path:
    sys.path.insert(0, str(_LLM_DIR))

import run_gemini_injest_db as inj  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_LWA_DB = Path(os.getenv("LWA_DB_PATH", str(REPO_ROOT / "dbscripts" / "lwa_data.db")))

# Tables that carry a YYYY-MM-DD `date` column in lwa_data.db (see dbscripts/append_dataset.py).
DATE_TABLES = (
    "spec_daily",
    "spec_hourly",
    "spec_daily_fits",
    "img_lev1_mfs",
    "img_lev15_mfs",
    "img_lev1_fch",
    "img_lev15_fch",
    "movies",
)

_PLACEHOLDER_SUMMARIES = frozenset(
    {
        "",
        "template text",
    }
)


class _TeeStdout:
    """Write to the real stdout and a log file (UTF-8)."""

    def __init__(self, console: TextIO, log_file: IO[str]) -> None:
        self._console = console
        self._log = log_file

    def write(self, s: str) -> int:
        self._console.write(s)
        self._log.write(s)
        return len(s)

    def flush(self) -> None:
        self._console.flush()
        self._log.flush()

    def isatty(self) -> bool:
        return self._console.isatty()


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def distinct_dates_from_lwa_db(lwa_db_path: Path) -> list[str]:
    """All distinct date keys, sorted newest first (ISO dates sort lexicographically)."""
    conn = sqlite3.connect(str(lwa_db_path))
    try:
        dates: set[str] = set()
        cur = conn.cursor()
        for table in DATE_TABLES:
            try:
                cur.execute(f"SELECT DISTINCT date FROM {table}")
            except sqlite3.OperationalError:
                continue
            for (d,) in cur.fetchall():
                if d and isinstance(d, str):
                    dates.add(d.strip())
        return sorted(dates, reverse=True)
    finally:
        conn.close()


def existing_summary_nonempty(ai_db_path: Path, date_iso: str) -> bool:
    """True if ai_summary has a row for date_iso with a non-placeholder summary."""
    if not ai_db_path.is_file():
        return False
    conn = sqlite3.connect(str(ai_db_path))
    try:
        cur = conn.cursor()
        cur.execute("SELECT summary FROM ai_summary WHERE date = ?", (date_iso,))
        row = cur.fetchone()
        if not row:
            return False
        s = (row[0] or "").strip()
        return s.lower() not in {x.lower() for x in _PLACEHOLDER_SUMMARIES} and len(s) > 0
    finally:
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Ingest Gemini summaries for all dates found in lwa_data.db (newest first)."
    )
    parser.add_argument("--lwa-db", default=str(DEFAULT_LWA_DB), help="Path to lwa_data.db.")
    parser.add_argument("--prompt", default=str(inj.DEFAULT_PROMPT_PATH), help="Prompt text file.")
    parser.add_argument("--db", default=str(inj.DEFAULT_DB_PATH), help="Path to ai_summary.db.")
    parser.add_argument("--model", default=inj.DEFAULT_MODEL, help="Gemini model name.")
    parser.add_argument(
        "--temperature",
        type=float,
        default=inj.DEFAULT_TEMPERATURE,
        help="Generation temperature.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Do not call Gemini or write ai_summary.db.")
    parser.add_argument(
        "--skip-existing",
        action="store_true",
        help="Skip dates that already have a non-empty, non-placeholder summary in ai_summary.db.",
    )
    parser.add_argument(
        "--min-date",
        metavar="YYYY-MM-DD",
        default="",
        help="Only process dates on or after this (inclusive).",
    )
    parser.add_argument(
        "--max-date",
        metavar="YYYY-MM-DD",
        default="",
        help="Only process dates on or before this (inclusive).",
    )
    parser.add_argument("--limit", type=int, default=0, help="Process at most this many dates (0 = no limit).")
    parser.add_argument(
        "--fail-fast",
        action="store_true",
        help="Stop the batch on the first Gemini or empty-response failure (exit 2 or 3).",
    )
    parser.add_argument(
        "--run-log",
        default=str(_LLM_DIR / "run.log"),
        help="Append full stdout mirror (same lines as the console).",
    )
    parser.add_argument(
        "--run-err",
        default=str(_LLM_DIR / "run.err"),
        help="Append one line per problematic date (TSV: time, date, reason).",
    )
    args = parser.parse_args()

    log_path = Path(args.run_log)
    err_path = Path(args.run_err)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    err_path.parent.mkdir(parents=True, exist_ok=True)

    exit_code = 0
    log_f: IO[str] | None = None
    err_f: IO[str] | None = None
    old_stdout = sys.stdout

    def err_line(date_iso: str, reason: str) -> None:
        if err_f is not None:
            err_f.write(f"{_utc_stamp()}\t{date_iso}\t{reason}\n")
            err_f.flush()

    try:
        log_f = open(log_path, "a", encoding="utf-8")
        err_f = open(err_path, "a", encoding="utf-8")
        log_f.write(f"\n===== run start {_utc_stamp()} pid={os.getpid()} =====\n")
        log_f.flush()
        err_f.write(f"\n===== run start {_utc_stamp()} =====\n")
        err_f.flush()

        sys.stdout = _TeeStdout(old_stdout, log_f)

        lwa_db = Path(args.lwa_db)
        if not lwa_db.is_file():
            print(f"[ERROR] lwa_data.db not found: {lwa_db}")
            err_line("-", f"lwa_db_missing:{lwa_db}")
            exit_code = 1
            return exit_code

        prompt_path = Path(args.prompt)
        if not prompt_path.is_file():
            print(f"[ERROR] Prompt file not found: {prompt_path}")
            err_line("-", f"prompt_missing:{prompt_path}")
            exit_code = 1
            return exit_code

        min_d = args.min_date.strip() or None
        max_d = args.max_date.strip() or None

        all_dates = distinct_dates_from_lwa_db(lwa_db)
        dates: list[str] = []
        for d in all_dates:
            if min_d is not None and d < min_d:
                continue
            if max_d is not None and d > max_d:
                continue
            dates.append(d)

        if args.limit and args.limit > 0:
            dates = dates[: args.limit]

        print(f"[INFO] lwa db: {lwa_db}")
        print(f"[INFO] run.log: {log_path.resolve()}")
        print(f"[INFO] run.err: {err_path.resolve()}")
        print(f"[INFO] distinct dates in lwa db (after filters): {len(dates)} (newest → oldest)")
        if dates:
            print(f"[INFO] first: {dates[0]}, last: {dates[-1]}")
        else:
            print("[WARN] No dates to process.")
            exit_code = 0
            return exit_code

        ai_db_path = Path(args.db)

        ok = skip_png = skip_exist = err_api = err_empty = 0
        for i, date_iso in enumerate(dates, start=1):
            print(f"\n[INFO] --- {i}/{len(dates)} {date_iso} ---")
            if args.skip_existing and existing_summary_nonempty(ai_db_path, date_iso):
                print(f"[INFO] skip-existing: already have summary for {date_iso}")
                skip_exist += 1
                continue
            try:
                yyyymmdd = inj.date_iso_to_yyyymmdd(date_iso)
            except ValueError as exc:
                print(f"[WARN] bad date key in lwa db, skipping: {date_iso!r} ({exc})")
                err_line(date_iso, f"bad_date_key:{exc}")
                skip_png += 1
                continue

            rc = inj.ingest_date_yyyymmdd(
                yyyymmdd,
                prompt_path=prompt_path,
                ai_db_path=ai_db_path,
                model=args.model,
                temperature=args.temperature,
                dry_run=args.dry_run,
                quiet=False,
            )
            if rc == 0:
                ok += 1
            elif rc == 1:
                skip_png += 1
                err_line(date_iso, "no_hourly_pngs_or_ingest_skip")
            elif rc == 2:
                err_api += 1
                err_line(date_iso, "gemini_error")
                if args.fail_fast:
                    print(f"[ERROR] fail-fast: stopping after Gemini failure on {date_iso}")
                    exit_code = 2
                    break
            elif rc == 3:
                err_empty += 1
                err_line(date_iso, "empty_gemini_response")
                if args.fail_fast:
                    print(f"[ERROR] fail-fast: stopping after empty Gemini response on {date_iso}")
                    exit_code = 3
                    break

        print(
            "\n[INFO] batch done: "
            f"ok={ok}, skip_no_png_or_bad={skip_png}, skip_existing={skip_exist}, "
            f"gemini_errors={err_api}, empty_response={err_empty}"
        )
        if exit_code == 0 and (err_api or err_empty):
            exit_code = 2
        return exit_code
    finally:
        sys.stdout = old_stdout
        if log_f is not None:
            log_f.write(f"===== run end exit={exit_code} {_utc_stamp()} =====\n")
            log_f.flush()
            log_f.close()
        if err_f is not None:
            err_f.flush()
            err_f.close()


if __name__ == "__main__":
    raise SystemExit(main())
