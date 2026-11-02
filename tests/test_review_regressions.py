import hashlib
import json
import os
import pathlib
import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import datetime
from unittest.mock import patch

from backend import database
from dbscripts import backfill_index as index, backfill_movies as movies
from dbscripts import generate_daily_movie as legacy
from dbscripts.build_db_fnames import init_db

DAY = '2023-05-02'
HASH = 'a' * 64
SOURCE = 'b' * 64
INFO = {'status': 'complete', 'provenance': {}, 'input_manifest_sha256': HASH, 'source_manifest_sha256': SOURCE}

class ReviewRegressions(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = pathlib.Path(self.tmp.name)
        self.db = self.root / 'test.db'
        self.conn = sqlite3.connect(self.db)
        init_db(self.conn)
        self.addCleanup(self.conn.close)

    def image(self, name='ovro-lwa.lev1_mfs_10s.2023-05-02T120000Z.image_I.hdf'):
        d = self.root / 'images/lev1/2023/05/02'
        d.mkdir(parents=True, exist_ok=True)
        p = d / name
        p.write_bytes(b'fixture')
        return p

    def test_report_rejects_existing_file_and_symlink_aliases_without_damage(self):
        source = self.image()
        plan = self.root/'plan.json'
        plan.write_text(json.dumps({'days': {DAY: INFO}}))
        hardlink = self.root/'hardlink'
        os.link(source, hardlink)
        symlink = self.root/'symlink'
        symlink.symlink_to(source)
        for target in (self.db, plan, source, hardlink, symlink, self.root/'existing', self.root/'dangling'):
            if target.name == 'existing': target.write_text('keep')
            if target.name == 'dangling': target.symlink_to(self.root/'missing')
            before = target.read_bytes() if not target.is_symlink() else None
            args = ['--plan',str(plan),'--db',str(self.db),'--img-root',str(self.root/'images'), '--movies-root',str(self.root/'movies'),'--report',str(target)]
            with self.subTest(target=target), self.assertRaises((FileExistsError, ValueError)):
                index.main(args)
            if before is not None: self.assertEqual(target.read_bytes(), before)

    def test_missing_database_is_not_created(self):
        plan = self.root/'plan.json'
        plan.write_text(json.dumps({'days': {DAY: INFO}}))
        missing = self.root/'missing.db'
        with self.assertRaises(sqlite3.OperationalError):
            index.main(['--plan',str(plan),'--db',str(missing),'--movies-root',str(self.root),'--report',str(self.root/'report')])
        self.assertFalse(missing.exists())

    def test_reconcile_only_selected_day_and_fail_closed_empty_scan(self):
        p = self.image()
        self.conn.executemany('INSERT INTO img_lev1_mfs VALUES (?,?)', [(DAY,DAY+' 12:00:10'), ('2023-05-03','2023-05-03 12:00:00')])
        self.conn.commit()
        index.index_day(self.conn, DAY, INFO, self.root/'images', self.root/'movies', apply=True)
        self.assertEqual(self.conn.execute('SELECT datetime FROM img_lev1_mfs ORDER BY datetime').fetchall(), [(DAY+' 12:00:00',), ('2023-05-03 12:00:00',)])
        self.assertTrue(p.exists())
        p.unlink()
        with self.assertRaises(ValueError): index.index_day(self.conn, DAY, INFO, self.root/'images', self.root/'movies', apply=True)
        self.assertEqual(self.conn.execute('SELECT count(*) FROM img_lev1_mfs').fetchone()[0],2)
        p.parent.rmdir()
        with self.assertRaises(FileNotFoundError): index.index_day(self.conn, DAY, INFO, self.root/'images', self.root/'movies', apply=True)

    def test_first_day_failure_rolls_back_schema_and_rows(self):
        self.image()
        with patch.object(index, 'refresh_day', side_effect=RuntimeError('failure')):
            with self.assertRaises(RuntimeError): index.index_day(self.conn, DAY, INFO, self.root/'images', self.root/'movies', apply=True)
        self.assertNotIn('dir', [r[1] for r in self.conn.execute('PRAGMA table_info(img_lev1_mfs)')])
        self.assertEqual(self.conn.execute("SELECT count(*) FROM sqlite_master WHERE name='portal_backfill_days'").fetchone()[0],0)
        self.assertEqual(self.conn.execute('SELECT count(*) FROM img_lev1_mfs').fetchone()[0],0)

    def test_receipt_bound_to_plan(self):
        out = self.root/'movies/2023/ovro-lwa-352.synop_mfs_image_I_movie_20230502.mp4'
        out.parent.mkdir(parents=True)
        out.write_bytes(b'movie')
        receipt = {'status':'published','date':DAY,'path':str(out),'sha256':hashlib.sha256(out.read_bytes()).hexdigest(),'frames':1, 'product_status':'complete', 'input_manifest_sha256':HASH, 'source_manifest_sha256':SOURCE}
        path = pathlib.Path(str(out)+'.backfill.json')
        for key in ('product_status','input_manifest_sha256','source_manifest_sha256'):
            bad = dict(receipt, **{key:'different'})
            path.write_text(json.dumps(bad))
            with self.subTest(key=key), self.assertRaises(ValueError): index.index_day(self.conn,DAY,INFO,self.root/'images',self.root/'movies',mode='movies',apply=True)
        path.write_text(json.dumps(receipt))
        with self.assertRaises((ValueError,KeyError)): index.index_day(self.conn,DAY,{'status':'complete'},self.root/'images',self.root/'movies',mode='movies')
        index.index_day(self.conn,DAY,INFO,self.root/'images',self.root/'movies',mode='movies',apply=True)

    def test_manifest_date_and_frame_dates_checked_before_resume(self):
        manifest = self.root/'day.json'
        data = {'date':DAY,'status':'complete','source_manifest_sha256':SOURCE,'frames':[{'path':str(self.root/'ovro-lwa.lev1_mfs_10s.2023-05-03T000000Z.image_I.png'),'sha256':HASH,'observed':'2023-05-03T00:00:00Z'}]}
        manifest.write_text(json.dumps(data))
        digest = hashlib.sha256(manifest.read_bytes()).hexdigest()
        out = self.root/'movies/2023/ovro-lwa-352.synop_mfs_image_I_movie_20230502.mp4'
        out.parent.mkdir(parents=True)
        out.write_bytes(b'movie')
        pathlib.Path(str(out)+'.backfill.json').write_text(json.dumps({'status':'published','input_manifest_sha256':digest,'sha256':hashlib.sha256(out.read_bytes()).hexdigest()}))
        for expected in ('2023-05-03', DAY):
            with self.subTest(expected=expected), self.assertRaises(ValueError): movies.process_day(manifest,digest,self.root/'work',self.root/'movies',self.root,expected_date=expected)
        self.assertFalse((self.root/'work').exists())

    def test_batch_rejects_manifest_for_a_different_day(self):
        frames = self.root/'frames'
        frames.mkdir()
        manifest = frames/(DAY+'.json')
        manifest.write_text(json.dumps({'date':'2023-05-03','status':'complete','source_manifest_sha256':SOURCE,'frames':[{'path':'/frame','sha256':HASH,'observed':'2023-05-03T00:00:00'}]}))
        summary = self.root/'summary.json'
        summary.write_text(json.dumps({'days':{DAY:{'manifest_sha256':hashlib.sha256(manifest.read_bytes()).hexdigest()}}}))
        self.assertEqual(movies.main(['--summary',str(summary),'--frames-dir',str(frames),'--work',str(self.root/'work'),'--movies-root',str(self.root/'movies'),'--source-root',str(self.root),'--jobs','1']),1)
        self.assertFalse((self.root/'movies').exists())

    def test_observed_and_source_metadata_required_before_resume(self):
        path = self.root/'frame.json'
        frame = {'path':'ovro-lwa.lev1_mfs_10s.2023-05-02T120000Z.image_I.png', 'sha256':HASH, 'observed':'2023-05-02T12:00:00'}
        data = {'date':DAY,'status':'complete','source_manifest_sha256':SOURCE,'frames':[frame]}
        for mutation in ('cross_day','missing_observed','missing_source'):
            current = json.loads(json.dumps(data))
            if mutation == 'cross_day': current['frames'][0]['observed'] = '2023-05-03T00:00:00'
            if mutation == 'missing_observed': del current['frames'][0]['observed']
            if mutation == 'missing_source': del current['source_manifest_sha256']
            path.write_text(json.dumps(current))
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                movies.process_day(path,hashlib.sha256(path.read_bytes()).hexdigest(),self.root/'work',self.root/'movies',self.root,expected_date=DAY)
        self.assertFalse((self.root/'work').exists())

    def test_index_migration_rollback_and_query_plans(self):
        with patch.object(index, 'TABLES', ('img_lev1_mfs', 'missing_table')):
            with self.assertRaises(sqlite3.OperationalError): index.prepare_indexes(self.conn)
        self.assertFalse(self.conn.execute("SELECT 1 FROM sqlite_master WHERE name='idx_img_lev1_mfs_date'").fetchone())
        index.prepare_indexes(self.conn)
        for table in index.COUNTS:
            details = ' '.join(row[3] for row in self.conn.execute('EXPLAIN QUERY PLAN SELECT COUNT(*) FROM '+table+' WHERE date=?',(DAY,)))
            self.assertIn('SEARCH', details, (table, details))

    def test_legacy_ignores_q_u_and_other_polarizations(self):
        d = self.root/'2023/05/02'
        d.mkdir(parents=True)
        names = [f'ovro-lwa.synop_mfs_10s.2023-05-02T12000{i}Z.image_{p}.png' for i,p in enumerate('IQUV')]
        for n in names: (d/n).touch()
        self.assertEqual([pathlib.Path(x).name for x in legacy._pngs_for_daily_window(datetime(2023,5,2),str(self.root))], names[:1])

    def test_max_rows_and_legacy_schema_fallback(self):
        self.conn.executemany('INSERT INTO img_lev1_mfs VALUES (?,?)', [(DAY,DAY+f' 12:00:{i:02}') for i in (0,10,20)])
        self.conn.commit()
        with patch.object(database,'LWA_DB_PATH',str(self.db)):
            rows, truncated = database.query_imaging(DAY+' 12:00:00',DAY+' 12:00:20','lev1_mfs',max_rows=2)
            self.assertTrue(truncated)
            self.assertEqual(len(rows),2)
            self.assertTrue(rows[0][1].endswith('2023-05-02T120000Z.image_I.hdf'))
            rows, truncated = database.query_imaging(DAY+' 12:00:00',DAY+' 12:00:20','lev1_mfs',max_rows=3)
            self.assertFalse(truncated)
            self.assertEqual(len(rows),3)

    def test_preview_empty_message_is_about_previews(self):
        app = (pathlib.Path(__file__).resolve().parents[1]/'frontend/src/App.jsx').read_text()
        self.assertNotIn('No data for this day.',app)
        self.assertIn('No preview', app)
