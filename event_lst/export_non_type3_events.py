#!/usr/bin/env python3
"""
Extract non–Type III events from ai_summary.db Gemini markdown tables into CSV.

Usage:
  python event_lst/export_non_type3_events.py
  python event_lst/export_non_type3_events.py -o event_lst/non_type3_events.csv
"""
from __future__ import annotations

import argparse
import csv
import os
import re
import sqlite3
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = Path(os.getenv("AI_SUMMARY_DB_PATH", str(REPO_ROOT / "llm" / "ai_summary.db")))
DEFAULT_OUT = Path(__file__).resolve().parent / "non_type3_events.csv"

EVENTS_HEADER = re.compile(
    r"^\|\s*Event\s*#\s*\|",
    re.IGNORECASE,
)
TABLE_SEP = re.compile(r"^\|\s*[-:]+\s*\|")

CSV_FIELDS = (
    "date",
    "event_num",
    "begin_ut",
    "peak_ut",
    "end_ut",
    "freq_range_mhz",
    "peak_flux_sfu",
    "type_notes",
)


def is_placeholder_row(row: dict[str, str]) -> bool:
    notes = row["type_notes"].strip().lower()
    if "no qualifying" in notes or "none were detected" in notes or "no events" in notes:
        return True
    if "no solar bursts" in notes:
        return True
    begin = row["begin_ut"].strip()
    if begin in {"", "-", "—", "n/a", "na"}:
        return True
    return False


def is_type_iii_event(notes: str) -> bool:
    """True if the event row is classified as a Type III burst/group (exclude from output)."""
    n = notes.strip().lower()
    if not n:
        return False
    if "no qualifying" in n or "none were detected" in n or "no events" in n:
        return False
    # Combined Type I/III noise storms are kept (not pure Type III bursts).
    if re.search(r"type\s*i\s*/\s*iii", n):
        return False
    return bool(re.search(r"type\s*iii\b", n))


def _split_table_row(line: str) -> list[str]:
    parts = [p.strip() for p in line.strip().strip("|").split("|")]
    return parts


def parse_events_table(summary: str) -> list[dict[str, str]]:
    """Return event rows parsed from the ## Events markdown table."""
    if not summary:
        return []
    m = re.search(r"^##\s+Events\s*$", summary, re.MULTILINE | re.IGNORECASE)
    if not m:
        return []
    section = summary[m.end() :]
    # Stop at next top-level heading if any.
    nxt = re.search(r"^##\s+", section, re.MULTILINE)
    if nxt:
        section = section[: nxt.start()]

    rows: list[dict[str, str]] = []
    in_table = False
    for line in section.splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        if EVENTS_HEADER.match(line):
            in_table = True
            continue
        if not in_table:
            continue
        if TABLE_SEP.match(line):
            continue
        cells = _split_table_row(line)
        if len(cells) < 7:
            continue
        notes = cells[6]
        if re.match(r"^[-:]+$", notes):
            continue
        rows.append(
            {
                "event_num": cells[0],
                "begin_ut": cells[1],
                "peak_ut": cells[2],
                "end_ut": cells[3],
                "freq_range_mhz": cells[4],
                "peak_flux_sfu": cells[5],
                "type_notes": notes,
            }
        )
    return rows


def load_summaries(db_path: Path) -> list[tuple[str, str]]:
    conn = sqlite3.connect(str(db_path))
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT date, summary FROM ai_summary WHERE summary IS NOT NULL ORDER BY date"
        )
        return [(row[0], row[1] or "") for row in cur.fetchall()]
    finally:
        conn.close()


def export_non_type3(db_path: Path, out_path: Path) -> int:
    if not db_path.is_file():
        print(f"[ERROR] Database not found: {db_path}", file=sys.stderr)
        return 1

    records: list[dict[str, str]] = []
    days_with_events = 0
    for date_iso, summary in load_summaries(db_path):
        events = parse_events_table(summary)
        kept = [
            e
            for e in events
            if not is_type_iii_event(e["type_notes"]) and not is_placeholder_row(e)
        ]
        if kept:
            days_with_events += 1
        for e in kept:
            records.append({"date": date_iso, **e})

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(records)

    print(f"[INFO] db: {db_path}")
    print(f"[INFO] wrote {len(records)} non–Type III event(s) from {days_with_events} day(s) → {out_path}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Export non–Type III events from ai_summary.db to CSV."
    )
    parser.add_argument("--db", default=str(DEFAULT_DB), help="Path to ai_summary.db")
    parser.add_argument("-o", "--output", default=str(DEFAULT_OUT), help="Output CSV path")
    args = parser.parse_args()
    return export_non_type3(Path(args.db), Path(args.output))


if __name__ == "__main__":
    raise SystemExit(main())
