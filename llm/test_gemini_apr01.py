#!/usr/bin/env python3
"""
Test Gemini daily-summary prompting using OVRO-LWA hourly PNGs.

Default dataset:
  /common/lwa/spec_v2/hourly/202604/01_*.png

Default prompt:
  llm/prompt_example.txt

Usage examples:
  python llm/test_gemini_apr01.py
  python llm/test_gemini_apr01.py --model gemini-2.5-flash-lite
  python llm/test_gemini_apr01.py --dry-run
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import List


DEFAULT_GLOB = "/common/lwa/spec_v2/hourly/202604/01_*.png"
DEFAULT_PROMPT_PATH = Path(__file__).resolve().parent / "prompt_example.txt"
DEFAULT_MODEL = "gemini-3-flash-preview"
DEFAULT_TEMPERATURE = 0.3


def load_prompt(prompt_path: Path) -> str:
    text = prompt_path.read_text(encoding="utf-8")
    # Keep compatibility with placeholders in the prompt template.
    threshold = float(os.getenv("BURST_STRONG_FLUX_THRESHOLD_SFU", "100"))
    text = text.replace("{BURST_STRONG_FLUX_THRESHOLD_SFU:g}", f"{threshold:g}")
    return text


def gather_images(pattern: str) -> List[Path]:
    from glob import glob

    return [Path(p) for p in sorted(glob(pattern))]


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Gemini on April 1, 2026 OVRO-LWA hourly PNGs.")
    parser.add_argument("--image-glob", default=DEFAULT_GLOB, help="Glob for input PNG images.")
    parser.add_argument("--prompt", default=str(DEFAULT_PROMPT_PATH), help="Prompt text file path.")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="Gemini model name.")
    parser.add_argument(
        "--temperature",
        type=float,
        default=DEFAULT_TEMPERATURE,
        help="Generation temperature (lower = less creative, more deterministic).",
    )
    parser.add_argument(
        "--output-dir",
        default=str(Path(__file__).resolve().parent / "outputs"),
        help="Directory for output artifacts.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print payload summary only; do not call Gemini API.",
    )
    args = parser.parse_args()

    prompt_path = Path(args.prompt)
    image_paths = gather_images(args.image_glob)
    if not image_paths:
        print(f"[ERROR] No images matched: {args.image_glob}")
        return 1
    if not prompt_path.is_file():
        print(f"[ERROR] Prompt file not found: {prompt_path}")
        return 1

    prompt = load_prompt(prompt_path)
    print(f"[INFO] Found {len(image_paths)} image(s).")
    print(f"[INFO] Prompt file: {prompt_path}")
    print(f"[INFO] Model: {args.model}")
    print(f"[INFO] Temperature: {args.temperature}")
    print(f"[INFO] First image: {image_paths[0]}")
    print(f"[INFO] Last image: {image_paths[-1]}")

    if args.dry_run:
        print("[INFO] Dry run complete.")
        return 0

    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        print("[ERROR] GEMINI_API_KEY is not set.")
        return 2

    try:
        from google import genai
    except Exception as exc:  # pragma: no cover
        print(f"[ERROR] google-genai import failed: {exc}")
        return 3

    client = genai.Client(api_key=api_key)

    parts = [{"text": prompt}]
    for image_path in image_paths:
        img_bytes = image_path.read_bytes()
        parts.append(
            {
                "inline_data": {
                    "mime_type": "image/png",
                    "data": img_bytes,
                }
            }
        )

    print("[INFO] Sending request to Gemini...")
    response = client.models.generate_content(
        model=args.model,
        contents=[{"role": "user", "parts": parts}],
        config={"temperature": args.temperature},
    )
    text = (getattr(response, "text", "") or "").strip()

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_txt = out_dir / f"gemini_apr01_{stamp}.txt"
    out_meta = out_dir / f"gemini_apr01_{stamp}.json"

    out_txt.write_text(text + "\n", encoding="utf-8")
    out_meta.write_text(
        json.dumps(
            {
                "timestamp_utc": stamp,
                "model": args.model,
                "temperature": args.temperature,
                "prompt_path": str(prompt_path),
                "image_glob": args.image_glob,
                "image_count": len(image_paths),
                "images": [str(p) for p in image_paths],
                "output_text_file": str(out_txt),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    print(f"[INFO] Saved summary: {out_txt}")
    print(f"[INFO] Saved metadata: {out_meta}")
    print("\n===== GEMINI RESPONSE =====\n")
    print(text)
    print("\n===========================")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

