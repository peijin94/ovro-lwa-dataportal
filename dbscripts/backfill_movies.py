#!/usr/bin/env python3
"""Build resumable movies from exact, hash-audited per-day frame manifests.

No source file is changed. Each movie uses every published frame in its
audited manifest. An explicit policy permits historical web-day folders
that include the following UTC morning up to 03:00. Publish
into a new versioned movie root so old URLs and owners' files remain intact.
"""
import hashlib
import json
import os
import re
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    from .generate_daily_movie import generate_daily_movie, _movie_path, _extract_timestamp
except ImportError:
    from generate_daily_movie import generate_daily_movie, _movie_path, _extract_timestamp


def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def atomic_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix='.json-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as f:
            json.dump(payload, f, indent=2)
            f.write('\n')
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, 0o664)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def process_day(manifest, expected_sha, work_root, movies_root, source_root, threads=2, *, expected_date):
    manifest = Path(manifest)
    raw = manifest.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if digest != expected_sha:
        raise ValueError('Frame manifest hash mismatch')
    data = json.loads(raw)
    date = data['date']
    day = datetime.strptime(date, '%Y-%m-%d')
    if date != expected_date or day.strftime('%Y-%m-%d') != date or data['status'] not in ('complete', 'published_with_gaps', 'event_sync'):
        raise ValueError('Invalid date or publication status')
    if not isinstance(data.get('source_manifest_sha256'), str) or not re.fullmatch(r'[0-9a-f]{64}', data['source_manifest_sha256']):
        raise ValueError('Invalid source manifest hash')
    if not data['frames']:
        raise ValueError('No frames in manifest')
    policy = data.get('day_policy', 'utc_day')
    if policy not in ('utc_day', 'web_day_through_next_03utc'):
        raise ValueError('Unknown movie day policy')
    end = day + timedelta(days=1, hours=3 if policy == 'web_day_through_next_03utc' else 0)
    for entry in data['frames']:
        stamp = _extract_timestamp(entry['path'])
        if stamp is None or not day <= stamp < end:
            raise ValueError(f'Frame timestamp outside declared day window: {entry["path"]}')
        observed = entry.get('observed')
        try:
            observed_stamp = datetime.fromisoformat(observed.replace('Z', '+00:00'))
            if observed_stamp.tzinfo is None:
                observed_stamp = observed_stamp.replace(tzinfo=timezone.utc)
            observed_utc = observed_stamp.astimezone(timezone.utc).replace(tzinfo=None)
            if not day <= observed_utc < end or observed_utc.replace(microsecond=0) != stamp:
                raise ValueError('Observed timestamp outside window or inconsistent with filename')
        except (AttributeError, ValueError) as exc:
            raise ValueError(f'Invalid observed UTC timestamp: {observed}') from exc
    movies_root = Path(movies_root).resolve()
    source_root = Path(source_root).resolve()
    work_root = Path(work_root).resolve()
    output = Path(_movie_path(day, str(movies_root)))
    receipt = Path(str(output) + '.backfill.json')
    if receipt.exists() and output.exists():
        old = json.loads(receipt.read_text())
        if old.get('status') == 'published' and old.get('input_manifest_sha256') == digest and old.get('date') == date and old.get('path') == str(output) and old.get('product_status') == data['status'] and old.get('source_manifest_sha256') == data.get('source_manifest_sha256') and old.get('sha256') == sha256(output):
            return old
    staging = work_root / 'staging'
    staging.mkdir(parents=True, exist_ok=True)
    # Hash while snapshotting; ffmpeg sees these immutable local copies, never
    # a changing NFS file. Discard only this invocation's TemporaryDirectory.
    with tempfile.TemporaryDirectory(prefix=date+'-', dir=staging) as tmp:
        frames = []
        for entry in data['frames']:
            source = Path(entry['path']).resolve()
            relative = source.relative_to(source_root)
            if tuple(relative.parts[:3]) != tuple(date.split('-')):
                raise ValueError(f'Frame outside selected web-day directory: {source}')
            if not source.is_file():
                raise ValueError(f'Missing frame: {source}')
            target = Path(tmp) / source.name
            if target.exists():
                raise ValueError(f'Duplicate frame basename: {source.name}')
            h = hashlib.sha256()
            with source.open('rb') as src, target.open('xb') as dst:
                for chunk in iter(lambda: src.read(1024 * 1024), b''):
                    h.update(chunk)
                    dst.write(chunk)
            if h.hexdigest() != entry['sha256']:
                raise ValueError(f'Frame hash mismatch: {source}')
            frames.append(str(target))
        if not generate_daily_movie(day, '', str(movies_root), 6, frames=frames, overwrite=True, threads=threads):
            raise RuntimeError('Movie generator did not produce output')
    result = {'status': 'published', 'date': date, 'path': str(output),
              'sha256': sha256(output), 'frames': len(data['frames']),
              'input_manifest_sha256': digest,
              'source_manifest_sha256': data.get('source_manifest_sha256'),
              'product_status': data['status'], 'fps': 6, 'day_policy': policy,
              'published_utc': datetime.now(timezone.utc).isoformat()}
    atomic_json(receipt, result)
    atomic_json(work_root / 'receipts' / (date + '.json'), result)
    return result


def main(argv=None):
    import argparse
    import fcntl
    from concurrent.futures import ThreadPoolExecutor, as_completed
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--summary', required=True)
    parser.add_argument('--frames-dir', required=True)
    parser.add_argument('--work', required=True)
    parser.add_argument('--movies-root', required=True)
    parser.add_argument('--source-root', required=True)
    parser.add_argument('--jobs', type=int, default=2)
    parser.add_argument('--threads', type=int, default=2)
    parser.add_argument('--days', help='Comma-separated explicit subset for a pilot')
    args = parser.parse_args(argv)
    if not 1 <= args.jobs <= 4 or not 1 <= args.threads <= 4:
        parser.error('jobs and threads must each be between 1 and 4')
    summary = json.loads(Path(args.summary).read_text())
    days = sorted(set(args.days.split(',')) if args.days else summary['days'])
    if not set(days).issubset(summary['days']):
        parser.error('Requested date absent from audited summary')
    work = Path(args.work)
    work.mkdir(parents=True, exist_ok=True)
    state = {'total': len(days), 'published': 0, 'failed': 0, 'days': {},
             'started_utc': datetime.now(timezone.utc).isoformat(), 'finished': False}
    with (work/'batch.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        atomic_json(work/'status.json', state)
        with ThreadPoolExecutor(max_workers=args.jobs) as pool:
            futures = {pool.submit(process_day, Path(args.frames_dir)/(day+'.json'),
                         summary['days'][day]['manifest_sha256'], work, args.movies_root,
                         args.source_root, args.threads, expected_date=day): day for day in days}
            for future in as_completed(futures):
                day = futures[future]
                try:
                    result = future.result()
                    state['published'] += 1
                    state['days'][day] = {'status': 'published', 'frames': result['frames']}
                except Exception as exc:
                    state['failed'] += 1
                    state['days'][day] = {'status': 'error', 'error': str(exc)}
                    atomic_json(work/'errors'/(day+'.json'), state['days'][day])
                atomic_json(work/'status.json', state)
                print(json.dumps({'date': day, **state['days'][day], 'published': state['published'],
                                  'failed': state['failed'], 'total': state['total']}), flush=True)
        state['finished'] = True
        state['finished_utc'] = datetime.now(timezone.utc).isoformat()
        atomic_json(work/'status.json', state)
    return 1 if state['failed'] else 0


if __name__ == '__main__':
    raise SystemExit(main())
