import hashlib
import json
import pathlib
import sqlite3
import tempfile
import unittest
from contextlib import closing
from dbscripts import backfill_movies, backfill_index
from dbscripts.build_db_fnames import init_db
from test_daily_movie import make_png


class RuntimeCases(unittest.TestCase):
    def test_explicit_observing_day_policy_keeps_early_next_day_frame(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=pathlib.Path(tmp)
            p=root/'source/2024/03/30/ovro-lwa.synop_mfs_10s.2024-03-31T010000Z.image_I.png'
            p.parent.mkdir(parents=True)
            make_png(p)
            m={'date':'2024-03-30','status':'complete','source_manifest_sha256':'a'*64,
               'day_policy':'web_day_through_next_03utc',
               'frames':[{'path':str(p),'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'observed':'2024-03-31T01:00:00'}]}
            manifest=root/'day.json'; manifest.write_text(json.dumps(m))
            result=backfill_movies.process_day(manifest,hashlib.sha256(manifest.read_bytes()).hexdigest(),
                root/'work',root/'out',root/'source',threads=1,expected_date='2024-03-30')
            self.assertEqual(result['frames'],1)
            self.assertEqual(result['day_policy'],'web_day_through_next_03utc')
            m['frames'][0]['observed']='2024-03-31T03:01:00'
            manifest.write_text(json.dumps(m))
            with self.assertRaises(ValueError):
                backfill_movies.process_day(manifest,hashlib.sha256(manifest.read_bytes()).hexdigest(),
                    root/'work',root/'out',root/'source',threads=1,expected_date='2024-03-30')
    def test_explicit_empty_exclusion_and_existing_alias_preference(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=pathlib.Path(tmp)
            with closing(sqlite3.connect(root/'data.db')) as conn:
                init_db(conn)
                conn.execute("INSERT INTO img_lev1_fch VALUES('2024-05-09','2024-05-09 17:00:03')")
                conn.commit()
                d=root/'images/lev1/2024/05/09'; d.mkdir(parents=True)
                canonical=d/'ovro-lwa-352.lev1_fch_10s.2024-05-09T170003Z.image_I.hdf'
                alias=d/'ovro-lwa.lev1_fch_10s.2024-05-09T170003Z.image_I.hdf'
                empty=d/'ovro-lwa.lev1_fch_10s.2024-05-09T170013Z.image_I.hdf'
                canonical.write_bytes(b'previously public canonical file'); alias.write_bytes(b'other preserved source'); empty.touch()
                info={'status':'published_with_gaps','provenance':{},'input_manifest_sha256':'b'*64,
                      'source_manifest_sha256':'a'*64,'excluded_empty_hdf':[str(empty)]}
                report=backfill_index.index_day(conn,'2024-05-09',info,root/'images',root/'movies',apply=True)
                self.assertEqual(conn.execute('SELECT dir FROM img_lev1_fch').fetchall(),[(str(canonical),)])
                self.assertEqual(len(report['excluded_empty_hdf']),1)
                self.assertEqual(len(report['duplicate_aliases']),1)
                self.assertTrue(alias.exists())
                empty.write_bytes(b'new repaired data')
                with self.assertRaises(ValueError):
                    backfill_index.index_day(conn,'2024-05-09',info,root/'images',root/'movies',apply=True)


if __name__=='__main__':
    unittest.main()
