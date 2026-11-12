#!/usr/bin/env python3
"""Generate daily OVRO-LWA synoptic image MP4 movies from PNG quicklooks."""
import argparse
import json
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
        if (timestamp and start_time <= timestamp <= end_time
                and "_mfs_" in os.path.basename(path)
                and (os.path.basename(path).endswith("Z.png")
                     or os.path.basename(path).endswith("Z.image_I.png"))):
            pngs.append(path)
    # Prefixes changed historically; lexical filename order is not time order.
    return sorted(pngs, key=_extract_timestamp)


def _movie_path(day: datetime, movies_root: str) -> str:
    yyyy = day.strftime("%Y")
    yyyymmdd = day.strftime("%Y%m%d")
    return os.path.join(
        movies_root,
        yyyy,
        f"{MOVIE_PREFIX}{yyyymmdd}.mp4",
    )


def validate_movie(path, expected_frames):
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_streams", "-of", "json", str(path)],
        check=True, capture_output=True, text=True,
    )
    stream = json.loads(result.stdout)["streams"][0]
    if (stream.get("codec_name") != "h264" or stream.get("pix_fmt") != "yuv420p"
            or int(stream.get("nb_frames", 0)) != expected_frames
            or float(stream.get("duration", 0)) <= 0
            or int(stream.get("width", 0)) <= 0 or int(stream.get("height", 0)) <= 0):
        raise RuntimeError(f"Movie validation failed: {stream}")
    return stream


def generate_daily_movie(day: datetime, png_root: str, movies_root: str, fps: int,
                         *, frames=None, overwrite=False, threads=2) -> bool:
    """Encode a day atomically. Explicit frames are NOT time-window filtered.

    Legacy cron calls retain their one-directory 12:00..next03:00 selection.
    Backfill callers supply ledger-audited frames for the entire UTC date.
    """
    if fps <= 0 or threads <= 0:
        raise ValueError("fps and threads must be positive")
    date_str = day.strftime("%Y-%m-%d")
    pngs = _pngs_for_daily_window(day, png_root) if frames is None else list(dict.fromkeys(map(str, frames)))
    ordered = []
    seen = set()
    for path in pngs:
        stamp = _extract_timestamp(path)
        name = os.path.basename(path)
        if stamp is None or '_mfs_' not in name or not (name.endswith('Z.png') or name.endswith('Z.image_I.png')):
            raise ValueError(f'Not a timestamped Stokes-I MFS PNG: {path}')
        if frames is not None and stamp in seen:
            raise ValueError(f'Duplicate movie timestamp: {stamp}')
        seen.add(stamp)
        ordered.append((stamp, path))
    # Legacy directory scans historically retained aliases. Keep that behavior;
    # explicit audited manifests must be deduplicated by their caller.
    pngs = [path for _, path in sorted(ordered)]
    if not pngs:
        print(f"[{date_str}] No selected PNGs.")
        return False
    output_path = _movie_path(day, movies_root)
    output_dir = os.path.dirname(output_path)
    os.makedirs(output_dir, exist_ok=True)
    if os.path.exists(output_path) and os.path.getsize(output_path) > 0 and not overwrite:
        print(f"[{date_str}] Movie already exists: {output_path}")
        return True
    dimensions = set()
    for png in pngs:
        with open(png, 'rb') as f:
            header = f.read(24)
        if len(header) != 24 or header[:8] != b'\x89PNG\r\n\x1a\n':
            raise ValueError(f'Invalid PNG header: {png}')
        dimensions.add(header[16:24])
    if len(dimensions) != 1:
        raise ValueError('Movie frames have inconsistent dimensions')
    fd, tmp_output_path = tempfile.mkstemp(prefix=".movie-", suffix=".tmp.mp4", dir=output_dir)
    os.close(fd)
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            for index, png in enumerate(pngs):
                os.symlink(os.path.abspath(png), os.path.join(temp_dir, f"{index:07d}.png"))
            cmd = ["ffmpeg", "-v", "error", "-nostdin", "-y", "-threads", str(threads),
                   "-framerate", str(fps), "-i", os.path.join(temp_dir, "%07d.png"),
                   "-filter_threads", "1", "-vf", "pad=ceil(iw/2)*2:ceil(ih/2)*2",
                   "-c:v", "libx264", "-threads", str(threads), "-pix_fmt", "yuv420p",
                   "-movflags", "+faststart", tmp_output_path]
            subprocess.run(cmd, check=True)
            validate_movie(tmp_output_path, len(pngs))
            os.chmod(tmp_output_path, 0o664)
            os.replace(tmp_output_path, output_path)
        print(f"[{date_str}] {len(pngs)} frames saved to: {output_path}", flush=True)
        return True
    finally:
        if os.path.exists(tmp_output_path):
            os.remove(tmp_output_path)


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
