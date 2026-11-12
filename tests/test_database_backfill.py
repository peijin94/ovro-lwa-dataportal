import pathlib
import sqlite3
from contextlib import closing
import tempfile
import unittest
from unittest.mock import patch
from backend import database
from dbscripts.build_db_fnames import init_db


class DatabaseBackfillTests(unittest.TestCase):
    def test_image_only_day_appears_in_date_picker(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp)/'test.db'
            with closing(sqlite3.connect(path)) as conn:
                init_db(conn)
                conn.execute("INSERT INTO spec_daily VALUES ('2023-07-19','/spectrum.png')")
                conn.execute("INSERT INTO datacount VALUES ('2023-05-02',0,0,0,1076,1076,1)")
                conn.execute("INSERT INTO datacount VALUES ('2023-05-03',0,0,0,0,0,0)")
                conn.commit()
            with patch.object(database, 'LWA_DB_PATH', str(path)):
                self.assertEqual(database.get_avail_dates(), ['2023-05-02','2023-07-19'])
    def test_query_uses_indexed_exact_filename_and_keeps_legacy_null_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp)/'test.db'
            with closing(sqlite3.connect(path)) as conn:
                init_db(conn)
                conn.execute('ALTER TABLE img_lev1_mfs ADD COLUMN dir TEXT')
                conn.execute("INSERT INTO img_lev1_mfs VALUES ('2024-01-11','2024-01-11 16:00:00','/actual/ovro-lwa.lev1_mfs_10s.2024-01-11T160000Z.image_I.hdf')")
                conn.execute("INSERT INTO img_lev1_mfs VALUES ('2024-01-11','2024-01-11 16:00:10',NULL)")
                conn.commit()
            with patch.object(database, 'LWA_DB_PATH', str(path)):
                rows, truncated = database.query_imaging('2024-01-11 16:00:00','2024-01-11 16:00:10','lev1_mfs')
                self.assertFalse(truncated)
                self.assertEqual(rows[0][1], '/actual/ovro-lwa.lev1_mfs_10s.2024-01-11T160000Z.image_I.hdf')
                self.assertTrue(rows[1][1].endswith('ovro-lwa-352.lev1_mfs_10s.2024-01-11T160010Z.image_I.hdf'))


if __name__ == '__main__':
    unittest.main()
