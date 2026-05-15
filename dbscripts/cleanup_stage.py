#!/usr/bin/env python3
"""Delete staged zip bundles and orphaned work dirs older than STAGE_RETENTION_HOURS."""
from __future__ import annotations

import os
import shutil
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.config import STAGE_READY_PATH, STAGE_WORK_PATH  # noqa: E402

RETENTION_HOURS = float(os.getenv("STAGE_RETENTION_HOURS", "12"))


def _older_than(path: Path, cutoff: float) -> bool:
    try:
        return path.stat().st_mtime < cutoff
    except OSError:
        return False


def _clean_ready(ready_dir: Path, cutoff: float) -> tuple[int, int]:
    """Remove *.zip files older than cutoff. Returns (removed_count, bytes_freed)."""
    removed = 0
    freed = 0
    if not ready_dir.is_dir():
        print(f"[SKIP] ready dir missing: {ready_dir}")
        return removed, freed
    for zip_path in ready_dir.glob("*.zip"):
        if not zip_path.is_file() or not _older_than(zip_path, cutoff):
            continue
        try:
            size = zip_path.stat().st_size
            zip_path.unlink()
            removed += 1
            freed += size
            print(f"[REMOVED] {zip_path}")
        except OSError as exc:
            print(f"[ERROR] {zip_path}: {exc}")
    return removed, freed


def _clean_work(work_dir: Path, cutoff: float) -> tuple[int, int]:
    """Remove immediate children (work trees) older than cutoff. Returns (removed_count, bytes_freed)."""
    removed = 0
    freed = 0
    if not work_dir.is_dir():
        print(f"[SKIP] work dir missing: {work_dir}")
        return removed, freed
    for child in work_dir.iterdir():
        if not _older_than(child, cutoff):
            continue
        try:
            if child.is_dir():
                size = sum(f.stat().st_size for f in child.rglob("*") if f.is_file())
                shutil.rmtree(child)
            else:
                size = child.stat().st_size
                child.unlink()
            removed += 1
            freed += size
            print(f"[REMOVED] {child}")
        except OSError as exc:
            print(f"[ERROR] {child}: {exc}")
    return removed, freed


def main() -> int:
    cutoff = time.time() - RETENTION_HOURS * 3600
    print(
        f"[INFO] stage cleanup retention={RETENTION_HOURS}h "
        f"ready={STAGE_READY_PATH} work={STAGE_WORK_PATH}"
    )
    zips, zip_bytes = _clean_ready(STAGE_READY_PATH, cutoff)
    dirs, dir_bytes = _clean_work(STAGE_WORK_PATH, cutoff)
    total_bytes = zip_bytes + dir_bytes
    print(
        f"[DONE] removed {zips} zip(s), {dirs} work item(s); "
        f"freed {total_bytes / (1024**2):.1f} MiB"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
