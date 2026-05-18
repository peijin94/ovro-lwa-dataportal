#!/usr/bin/env python3
"""Generate daily OVRO-LWA synoptic image MP4 movies from PNG quicklooks."""
import argparse
import os
import subprocess
import tempfile
from datetime import datetime, timedelta
from glob import glob

PNG_ROOT = "/common/webplots/lwa-data/qlook_images/slow/synop"
MOVIES_ROOT = "/common/webplots/lwa-data/qlook_daily/movies"
MOVIE_PREFIX = "ovro-lwa-352.synop_mfs_image_I_movie_"


def _parse_date(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%d")


def _extract_timestamp(path: str):
    base = os.path.basename(path)
    try:
        date_part = base.split("T", 1)[0].split(".")[-1]
        time_part = base.split("T", 1)[1][:6]
        return datetime.strptime(date_part + time_part, "%Y-%m-%d%H%M%S")
    except (IndexError, ValueError):
        return None


def _pngs_for_daily_window(day: datetime, png_root: str):
    yyyy, mm, dd = day.strftime("%Y"), day.strftime("%m"), day.strftime("%d")
    img_dir = os.path.join(png_root, yyyy, mm, dd)
    all_pngs = sorted(glob(os.path.join(img_dir, "*.png")))

    start_time = day.replace(hour=12, minute=0, second=0, microsecond=0)
    end_time = (day + timedelta(days=1)).replace(hour=3, minute=0, second=0, microsecond=0)

    pngs = []
    for path in all_pngs:
        timestamp = _extract_timestamp(path)
        if timestamp and start_time <= timestamp <= end_time:
            pngs.append(path)
    return pngs


def _movie_path(day: datetime, movies_root: str) -> str:
    yyyy = day.strftime("%Y")
    yyyymmdd = day.strftime("%Y%m%d")
    return os.path.join(
        movies_root,
        yyyy,
        f"{MOVIE_PREFIX}{yyyymmdd}.mp4",
    )


def generate_daily_movie(day: datetime, png_root: str, movies_root: str, fps: int) -> bool:
    date_str = day.strftime("%Y-%m-%d")
    pngs = _pngs_for_daily_window(day, png_root)
    if not pngs:
        print(f"[{date_str}] No PNGs in 12:00-03:00 window.")
        return False

    output_path = _movie_path(day, movies_root)
    output_dir = os.path.dirname(output_path)
    tmp_output_path = f"{output_path}.tmp.mp4"
    os.makedirs(output_dir, exist_ok=True)

    if os.path.exists(output_path):
        if os.path.getsize(output_path) == 0:
            print(f"[{date_str}] Removing empty movie before regeneration: {output_path}")
            os.remove(output_path)
        else:
            print(f"[{date_str}] Movie already exists: {output_path}")
            return True

    if os.path.exists(tmp_output_path):
        os.remove(tmp_output_path)

    print(f"[{date_str}] {len(pngs)} PNGs in time window.")
    with tempfile.TemporaryDirectory() as temp_dir:
        try:
            for index, png in enumerate(pngs):
                os.symlink(png, os.path.join(temp_dir, f"{index:04d}.png"))

            cmd = [
                "ffmpeg",
                "-loglevel",
                "warning",
                "-nostats",
                "-y",
                "-framerate",
                str(fps),
                "-i",
                os.path.join(temp_dir, "%04d.png"),
                "-vf",
                "pad=ceil(iw/2)*2:ceil(ih/2)*2",
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                tmp_output_path,
            ]
            subprocess.run(cmd, check=True)
            if not os.path.exists(tmp_output_path) or os.path.getsize(tmp_output_path) == 0:
                raise RuntimeError(f"ffmpeg did not create a non-empty movie: {tmp_output_path}")
            os.replace(tmp_output_path, output_path)
            print(f"[{date_str}] Movie saved to: {output_path}")
            return True
        except Exception:
            if os.path.exists(tmp_output_path):
                os.remove(tmp_output_path)
            raise


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate daily OVRO-LWA image MP4 movies.")
    parser.add_argument("--start", required=True, help="Start date, YYYY-MM-DD.")
    parser.add_argument("--end", required=True, help="End date, YYYY-MM-DD.")
    parser.add_argument("--png-root", default=PNG_ROOT, help=f"PNG root, default: {PNG_ROOT}")
    parser.add_argument("--out", default=MOVIES_ROOT, help=f"Movie output root, default: {MOVIES_ROOT}")
    parser.add_argument("--fps", type=int, default=6, help="Output movie frame rate.")
    args = parser.parse_args()

    start = _parse_date(args.start)
    end = _parse_date(args.end)
    if end < start:
        raise ValueError("--end must be on or after --start")

    ok = True
    current = start
    while current <= end:
        try:
            ok = generate_daily_movie(current, args.png_root, args.out, args.fps) and ok
        except Exception as exc:
            print(f"[{current.strftime('%Y-%m-%d')}] Movie generation failed: {exc}")
            ok = False
        current += timedelta(days=1)

    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
