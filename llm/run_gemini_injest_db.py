#!/usr/bin/env python3
"""
Generate a daily OVRO-LWA spectrogram summary with Gemini and store it in ai_summary.db.

For a calendar date given as yyyymmdd, loads hourly PNGs from:
  /common/lwa/spec_v2/hourly/{YYYYMM}/{DD}_*.png

Uses the same prompt and Gemini call pattern as llm/test_gemini_apr01.py.

Usage:
  export GEMINI_API_KEY=...
  python llm/run_gemini_injest_db.py --date 20260401

Optional:
  python llm/run_gemini_injest_db.py --date 20260401 --dry-run
  python llm/run_gemini_injest_db.py --date 20260401 --db /path/to/ai_summary.db
"""

from __future__ import annotations

import argparse
import os
import sqlite3
from datetime import datetime, timezone
from glob import glob
from pathlib import Path
from typing import List, Tuple


REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PROMPT_PATH = Path(__file__).resolve().parent / "prompt_example.txt"
DEFAULT_DB_PATH = Path(os.getenv("AI_SUMMARY_DB_PATH", str(REPO_ROOT / "llm" / "ai_summary.db")))
DEFAULT_MODEL = "gemini-3-flash-preview"
DEFAULT_TEMPERATURE = 0.3
SPEC_HOURLY_ROOT = "/common/lwa/spec_v2/hourly"


def parse_yyyymmdd(s: str) -> Tuple[str, str, str, str]:
    """Return (yyyymmdd, yyyymm, dd, date_iso YYYY-MM-DD)."""
    t = s.strip()
    if len(t) != 8 or not t.isdigit():
        raise ValueError(f"date must be yyyymmdd (8 digits), got {s!r}")
    yyyy, mm, dd = t[0:4], t[4:6], t[6:8]
    return t, f"{yyyy}{mm}", dd, f"{yyyy}-{mm}-{dd}"


def hourly_glob_for_date(yyyymmdd: str) -> str:
    _, yyyymm, dd, _ = parse_yyyymmdd(yyyymmdd)
    return f"{SPEC_HOURLY_ROOT}/{yyyymm}/{dd}_*.png"


def load_prompt(prompt_path: Path) -> str:
    text = prompt_path.read_text(encoding="utf-8")
    threshold = float(os.getenv("BURST_STRONG_FLUX_THRESHOLD_SFU", "100"))
    text = text.replace("{BURST_STRONG_FLUX_THRESHOLD_SFU:g}", f"{threshold:g}")
    return text


def gather_images(pattern: str) -> List[Path]:
    return [Path(p) for p in sorted(glob(pattern))]


def ensure_ai_summary_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS ai_summary (
            date TEXT PRIMARY KEY,
            summary TEXT NOT NULL
        )
        """
    )


def upsert_summary(conn: sqlite3.Connection, date_iso: str, summary: str) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO ai_summary (date, summary) VALUES (?, ?)",
        (date_iso, summary),
    )


def date_iso_to_yyyymmdd(date_iso: str) -> str:
    """Convert YYYY-MM-DD (lwa_data.db key) to yyyymmdd for hourly PNG glob."""
    parts = date_iso.strip().split("-")
    if len(parts) != 3:
        raise ValueError(f"expected YYYY-MM-DD, got {date_iso!r}")
    y, m, d = parts[0], parts[1], parts[2]
    if len(y) != 4 or len(m) != 2 or len(d) != 2 or not (y + m + d).isdigit():
        raise ValueError(f"expected YYYY-MM-DD, got {date_iso!r}")
    return f"{y}{m}{d}"


def run_gemini(
    prompt: str,
    image_paths: List[Path],
    model: str,
    temperature: float,
) -> str:
    try:
        from google import genai
    except Exception as exc:  # pragma: no cover
        raise RuntimeError(f"google-genai import failed: {exc}") from exc

    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is not set")

    client = genai.Client(api_key=api_key)
    parts: list = [{"text": prompt}]
    for image_path in image_paths:
        parts.append(
            {
                "inline_data": {
                    "mime_type": "image/png",
                    "data": image_path.read_bytes(),
                }
            }
        )
    response = client.models.generate_content(
        model=model,
        contents=[{"role": "user", "parts": parts}],
        config={"temperature": temperature},
    )
    return (getattr(response, "text", "") or "").strip()


def ingest_date_yyyymmdd(
    yyyymmdd: str,
    *,
    prompt_path: Path,
    ai_db_path: Path,
    model: str,
    temperature: float,
    dry_run: bool,
    quiet: bool = False,
) -> int:
    """
    Run Gemini for one UTC day and upsert into ai_summary.db.

    Returns 0 on success, 1 bad date / missing prompt / no PNGs, 2 Gemini error, 3 empty response.
    """
    log = (lambda *a, **k: None) if quiet else print

    try:
        _, _, _, date_iso = parse_yyyymmdd(yyyymmdd)
    except ValueError as e:
        log(f"[ERROR] {e}")
        return 1

    pattern = hourly_glob_for_date(yyyymmdd)
    image_paths = gather_images(pattern)

    if not prompt_path.is_file():
        log(f"[ERROR] Prompt file not found: {prompt_path}")
        return 1
    if not image_paths:
        log(f"[WARN] No images matched: {pattern} — skip {date_iso}")
        return 1

    prompt = load_prompt(prompt_path)
    log(f"[INFO] date (DB key): {date_iso}")
    log(f"[INFO] image glob: {pattern}")
    log(f"[INFO] images: {len(image_paths)} ({image_paths[0].name} … {image_paths[-1].name})")
    log(f"[INFO] model: {model}, temperature: {temperature}")
    log(f"[INFO] ai_summary db: {ai_db_path}")

    if dry_run:
        log("[INFO] Dry run; no API or DB write.")
        return 0

    try:
        text = run_gemini(prompt, image_paths, model, temperature)
    except Exception as exc:
        log(f"[ERROR] Gemini failed ({date_iso}): {exc}")
        return 2

    if not text:
        log(f"[ERROR] Empty response from Gemini ({date_iso}).")
        return 3

    ai_db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(ai_db_path))
    try:
        ensure_ai_summary_table(conn)
        upsert_summary(conn, date_iso, text)
        conn.commit()
    finally:
        conn.close()

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    log(f"[INFO] Saved summary for {date_iso} at {stamp}")
    if not quiet:
        print("\n===== PREVIEW (first 800 chars) =====\n")
        print(text[:800] + ("…" if len(text) > 800 else ""))
        print("\n=====================================")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run Gemini on one day's hourly PNGs and save markdown summary to ai_summary.db."
    )
    parser.add_argument("--date", required=True, metavar="yyyymmdd", help="UTC calendar day, e.g. 20260401.")
    parser.add_argument("--prompt", default=str(DEFAULT_PROMPT_PATH), help="Prompt text file path.")
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH), help="Path to ai_summary.db.")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="Gemini model name.")
    parser.add_argument(
        "--temperature",
        type=float,
        default=DEFAULT_TEMPERATURE,
        help="Generation temperature.",
    )
    parser.add_argument("--dry-run", action="store_true", help="List inputs only; do not call Gemini or write DB.")
    args = parser.parse_args()

    try:
        _, _, _, _ = parse_yyyymmdd(args.date)
    except ValueError as e:
        print(f"[ERROR] {e}")
        return 1

    return ingest_date_yyyymmdd(
        args.date,
        prompt_path=Path(args.prompt),
        ai_db_path=Path(args.db),
        model=args.model,
        temperature=args.temperature,
        dry_run=args.dry_run,
        quiet=False,
    )


if __name__ == "__main__":
    raise SystemExit(main())
