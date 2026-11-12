#!/usr/bin/env python3
"""Incrementally index explicit approved days; never rebuild the live database."""
import json
import sys
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

IMAGE_RE = re.compile(r'^ovro-lwa(?:-352)?\.lev1_(mfs|fch)_10s\.(\d{4}-\d{2}-\d{2})T(\d{6})Z\.image_I\.hdf$')
try:
    from .backfill_movies import sha256
    from .generate_daily_movie import _movie_path
except ImportError:
    from backfill_movies import sha256
    from generate_daily_movie import _movie_path

TABLES = ('img_lev1_mfs', 'img_lev1_fch')
COUNTS = ('spec_daily', 'spec_daily_fits', 'spec_hourly', *TABLES, 'movies')


def ensure_schema(conn):
    for table in TABLES:
        if 'dir' not in {r[1] for r in conn.execute('PRAGMA table_info('+table+')')}:
            conn.execute('ALTER TABLE '+table+' ADD COLUMN dir TEXT')
    conn.execute('''CREATE TABLE IF NOT EXISTS portal_backfill_days (
        date TEXT PRIMARY KEY, status TEXT NOT NULL, provenance TEXT NOT NULL, updated_utc TEXT NOT NULL)''')


def scan_images(day, image_root, preferred=None, excluded_empty=(), aliases=None):
    directory = Path(image_root) / 'lev1' / day.replace('-', '/')
    if not directory.is_dir():
        raise FileNotFoundError(directory)
    found = {'mfs': {}, 'fch': {}}
    preferred = preferred or {}
    aliases = aliases if aliases is not None else []
    excluded_empty = set(excluded_empty)
    for value in excluded_empty:
        p = Path(value)
        if p.parent != directory or not p.is_file() or p.stat().st_size != 0:
            raise ValueError(f'Empty-file exclusion no longer matches: {p}')
    for path in sorted(directory.iterdir()):
        match = IMAGE_RE.fullmatch(path.name)
        if not match:
            continue
        kind, date, time = match.groups()
        if date != day:
            raise ValueError(f'Filename/directory date mismatch: {path}')
        stamp = datetime.strptime(date+time, '%Y-%m-%d%H%M%S').strftime('%Y-%m-%d %H:%M:%S')
        if str(path) in excluded_empty:
            continue
        if not path.is_file() or path.stat().st_size == 0:
            raise ValueError(f'Not a nonempty HDF: {path}')
        path.resolve().relative_to(Path(image_root).resolve())
        if stamp in found[kind]:
            previous = found[kind][stamp]
            selected = preferred.get(kind, {}).get(stamp)
            if selected not in (previous, str(path)):
                raise ValueError(f'Duplicate HDF timestamp: {previous} and {path}')
            aliases.append({'datetime': stamp, 'kind': kind, 'selected': selected,
                            'not_indexed': str(path) if selected == previous else previous,
                            'reason': 'preserve existing public path selection'})
            found[kind][stamp] = selected
        else:
            found[kind][stamp] = str(path)
    if not any(found.values()):
        raise ValueError(f'No valid Stokes-I images in {directory}')
    return found


def prepare_indexes(conn):
    """One-time migration, separate from the short per-day transactions."""
    conn.execute('BEGIN')
    try:
        for table in (*TABLES, 'spec_hourly'):
            conn.execute('CREATE INDEX IF NOT EXISTS idx_'+table+'_date ON '+table+'(date)')
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def refresh_day(conn, day):
    counts = [conn.execute('SELECT COUNT(*) FROM '+t+' WHERE date=?', (day,)).fetchone()[0] for t in COUNTS]
    conn.execute('''INSERT INTO datacount VALUES (?,?,?,?,?,?,?) ON CONFLICT(date) DO UPDATE SET
        n_spec_daily=excluded.n_spec_daily, n_spec_daily_fits=excluded.n_spec_daily_fits,
        n_spec_hourly=excluded.n_spec_hourly, n_img_lev1_mfs=excluded.n_img_lev1_mfs,
        n_img_lev1_fch=excluded.n_img_lev1_fch, n_movies=excluded.n_movies''', [day]+counts)
    return dict(zip(('n_'+t for t in COUNTS), counts))


def index_day(conn, day, info, image_root, movies_root, mode='images', apply=False):
    parsed = datetime.strptime(day, '%Y-%m-%d')
    if parsed.strftime('%Y-%m-%d') != day or info['status'] not in ('complete','published_with_gaps','event_sync'):
        raise ValueError('Unapproved date/status')
    for key in ('input_manifest_sha256', 'source_manifest_sha256'):
        if not isinstance(info.get(key), str) or not re.fullmatch(r'[0-9a-f]{64}', info[key]):
            raise ValueError(f'Invalid plan {key}')
    if mode not in ('images', 'movies', 'all'):
        raise ValueError('Unknown indexing mode')
    aliases = []
    excluded_empty = info.get('excluded_empty_hdf', [])
    preferred = {}
    if mode in ('images', 'all'):
        for kind in ('mfs', 'fch'):
            table = 'img_lev1_'+kind
            path_column = 'dir' if 'dir' in {r[1] for r in conn.execute('PRAGMA table_info('+table+')')} else 'NULL'
            preferred[kind] = {}
            next_day = (parsed + timedelta(days=1)).strftime('%Y-%m-%d')
            for stamp, path in conn.execute('SELECT datetime,'+path_column+' FROM '+table+' WHERE datetime>=? AND datetime<?',
                                             (day+' 00:00:00', next_day+' 00:00:00')):
                old_time = datetime.strptime(stamp, '%Y-%m-%d %H:%M:%S')
                fallback = Path(image_root)/'lev1'/day.replace('-','/')/('ovro-lwa-352.lev1_'+kind+'_10s.'+old_time.strftime('%Y-%m-%dT%H%M%SZ')+'.image_I.hdf')
                preferred[kind][stamp] = path or str(fallback)
    found = scan_images(day, image_root, preferred, excluded_empty, aliases) if mode in ('images', 'all') else {}
    movie = None
    if mode in ('movies', 'all'):
        movie = Path(_movie_path(parsed, str(movies_root)))
        receipt = json.loads(Path(str(movie)+'.backfill.json').read_text())
        if (receipt.get('status') != 'published' or receipt.get('date') != day
                or receipt.get('path') != str(movie) or receipt.get('frames', 0) <= 0
                or not movie.is_file() or movie.stat().st_size <= 0
                or receipt.get('sha256') != sha256(movie)
                or receipt.get('product_status') != info['status']
                or receipt.get('input_manifest_sha256') != info['input_manifest_sha256']
                or receipt.get('source_manifest_sha256') != info['source_manifest_sha256']):
            raise ValueError(f'Movie receipt/hash mismatch: {movie}')
    report = {'date':day, 'status':info['status'], 'images':{k:len(v) for k,v in found.items()}, 'applied':apply,
              'excluded_empty_hdf': excluded_empty, 'duplicate_aliases': aliases}
    if not apply:
        return report
    conn.execute('BEGIN')
    try:
        ensure_schema(conn)
        for kind, rows in found.items():
            table = 'img_lev1_'+kind
            existing = dict(conn.execute('SELECT datetime,dir FROM '+table+' WHERE date=?', (day,)))
            for stamp, path in rows.items():
                if existing.get(stamp) and existing[stamp] != path:
                    raise ValueError(f'Existing exact-path conflict at {stamp}: {existing[stamp]} vs {path}')
            stale = [(day, stamp) for stamp in existing if stamp not in rows]
            conn.executemany('DELETE FROM '+table+' WHERE date=? AND datetime=?', stale)
            conn.executemany('INSERT INTO '+table+'(date,datetime,dir) VALUES(?,?,?) '
                             'ON CONFLICT(datetime) DO UPDATE SET dir=excluded.dir',
                             [(day, stamp, path) for stamp,path in rows.items()])
        if movie is not None:
            conn.execute('INSERT INTO movies(date,dir) VALUES(?,?) '
                         'ON CONFLICT(date) DO UPDATE SET dir=excluded.dir', (day, str(movie)))
            report['movie'] = str(movie)
        report['counts'] = refresh_day(conn, day)
        conn.execute('''INSERT INTO portal_backfill_days VALUES (?,?,?,?) ON CONFLICT(date) DO UPDATE SET
            status=excluded.status, provenance=excluded.provenance, updated_utc=excluded.updated_utc''',
            (day, info['status'], json.dumps(info.get('provenance',{}),sort_keys=True),datetime.now(timezone.utc).isoformat()))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return report


def main(argv=None):
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan', required=True)
    parser.add_argument('--db', required=True)
    parser.add_argument('--img-root', default='/nas7/ovro-lwa-data/hdf/slow')
    parser.add_argument('--movies-root', required=True)
    parser.add_argument('--mode', choices=['images','movies','all'], default='images')
    parser.add_argument('--report', required=True)
    parser.add_argument('--days', help='Comma-separated subset for a pilot')
    parser.add_argument('--apply', action='store_true', help='Opt in to writes; first prepares date indexes in a separate migration; default read-only')
    args=parser.parse_args(argv)
    plan=json.loads(Path(args.plan).read_text())
    days=sorted(set(args.days.split(',')) if args.days else plan['days'])
    if not days or not set(days).issubset(plan['days']):
        parser.error('Date list is empty or absent from plan')
    uri=Path(args.db).resolve().as_uri()+'?mode='+('rw' if args.apply else 'ro')
    conn=sqlite3.connect(uri, uri=True, timeout=60)
    failures=0
    try:
        # Exclusive creation rejects existing files, hard links, and dangling symlinks.
        with open(args.report, 'x') as out:
            if args.apply:
                print('Preparing date indexes (one-time migration)...', file=sys.stderr, flush=True)
                prepare_indexes(conn)
            for day in days:
                try:
                    info = dict(plan['days'][day])
                    source_hash = plan.get('source_manifest_sha256')
                    if source_hash is not None and info.get('source_manifest_sha256', source_hash) != source_hash:
                        raise ValueError('Plan source manifest hash mismatch')
                    info.setdefault('source_manifest_sha256', source_hash)
                    report=index_day(conn,day,info,Path(args.img_root),Path(args.movies_root),args.mode,args.apply)
                except Exception as exc:
                    conn.rollback()
                    report={'date':day,'error':str(exc),'applied':False}
                    failures+=1
                line=json.dumps(report)
                out.write(line+chr(10))
                out.flush()
                print(line,flush=True)
    finally:
        conn.close()
    return 1 if failures else 0


if __name__ == '__main__':
    raise SystemExit(main())
