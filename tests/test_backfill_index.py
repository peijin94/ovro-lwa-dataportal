import json
import pathlib
import sqlite3
from contextlib import closing
import tempfile
import unittest
from dbscripts.build_db_fnames import init_db


HASHES = {'input_manifest_sha256': 'a'*64, 'source_manifest_sha256': 'b'*64}


class BackfillIndexTests(unittest.TestCase):
    def test_images_index_exact_i_paths_idempotently_and_keep_other_days(self):
        from dbscripts import backfill_index as b
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            conn = sqlite3.connect(root/'test.db')
            init_db(conn)
            conn.execute("INSERT INTO img_lev1_mfs VALUES ('2023-01-01','2023-01-01 10:00:00')")
            conn.commit()
            daydir = root/'images/lev1/2024/01/11'
            daydir.mkdir(parents=True)
            mfs = daydir/'ovro-lwa.lev1_mfs_10s.2024-01-11T160000Z.image_I.hdf'
            fch = daydir/'ovro-lwa-352.lev1_fch_10s.2024-01-11T160000Z.image_I.hdf'
            v = daydir/'ovro-lwa.lev1_mfs_10s.2024-01-11T160010Z.image_V.hdf'
            for p in [mfs, fch, v]:
                p.write_bytes(b'test data; indexer reads names, not payload')
            for _ in range(2):
                b.index_day(conn, '2024-01-11', {'status':'published_with_gaps','provenance':{'run':'test'}, **HASHES},
                            root/'images', root/'movies', mode='images', apply=True)
            self.assertEqual(conn.execute("SELECT datetime,dir FROM img_lev1_mfs WHERE date='2024-01-11'").fetchall(),
                             [('2024-01-11 16:00:00', str(mfs))])
            self.assertEqual(conn.execute("SELECT n_img_lev1_mfs,n_img_lev1_fch FROM datacount WHERE date='2024-01-11'").fetchone(), (1,1))
            self.assertEqual(conn.execute("SELECT count(*) FROM img_lev1_mfs WHERE date='2023-01-01'").fetchone()[0], 1)
            self.assertEqual(conn.execute("SELECT status FROM portal_backfill_days WHERE date='2024-01-11'").fetchone()[0], 'published_with_gaps')
            conn.close()
    def test_movies_require_matching_receipt_before_indexing(self):
        import hashlib
        from dbscripts import backfill_index as b
        with tempfile.TemporaryDirectory() as tmp:
            root=pathlib.Path(tmp)
            conn=sqlite3.connect(root/'test.db')
            init_db(conn)
            output=root/'movies/2023/ovro-lwa-352.synop_mfs_image_I_movie_20230502.mp4'
            output.parent.mkdir(parents=True)
            output.write_bytes(b'output tested by renderer')
            info={'status':'complete','provenance':{}, **HASHES}
            with self.assertRaises((ValueError,FileNotFoundError)):
                b.index_day(conn,'2023-05-02',info,root/'images',root/'movies',mode='movies',apply=True)
            receipt={'status':'published','date':'2023-05-02','path':str(output),'sha256':hashlib.sha256(output.read_bytes()).hexdigest(),'frames':1076,'product_status':'complete',**HASHES}
            pathlib.Path(str(output)+'.backfill.json').write_text(json.dumps(receipt))
            b.index_day(conn,'2023-05-02',info,root/'images',root/'movies',mode='movies',apply=True)
            self.assertEqual(conn.execute('SELECT date,dir FROM movies').fetchall(), [('2023-05-02',str(output))])
            self.assertEqual(conn.execute('SELECT n_movies FROM datacount').fetchone()[0],1)
            conn.close()
    def test_cli_dry_run_does_not_mutate_database(self):
        import hashlib
        from dbscripts import backfill_index as b
        with tempfile.TemporaryDirectory() as tmp:
            root=pathlib.Path(tmp)
            db=root/'test.db'
            with closing(sqlite3.connect(db)) as conn:
                init_db(conn)
            d=root/'images/lev1/2023/05/02'
            d.mkdir(parents=True)
            (d/'ovro-lwa-352.lev1_mfs_10s.2023-05-02T201603Z.image_I.hdf').write_bytes(b'hdf fixture')
            plan=root/'plan.json'
            plan.write_text(json.dumps({'days':{'2023-05-02':{'status':'complete','provenance':{}, **HASHES}}}))
            before=hashlib.sha256(db.read_bytes()).hexdigest()
            args=['--plan',str(plan),'--db',str(db),'--img-root',str(root/'images'),
                  '--movies-root',str(root/'movies'),'--report',str(root/'report.jsonl')]
            self.assertEqual(b.main(args),0)
            self.assertEqual(hashlib.sha256(db.read_bytes()).hexdigest(),before)
            args[-1] = str(root/'apply-report.jsonl')
            self.assertEqual(b.main(args+['--apply']),0)
            with closing(sqlite3.connect(db)) as conn:
                self.assertEqual(conn.execute('SELECT count(*) FROM img_lev1_mfs').fetchone()[0],1)


if __name__ == '__main__':
    unittest.main()
