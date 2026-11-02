import hashlib
import json
import pathlib
import tempfile
import unittest
from test_daily_movie import make_png


class BackfillMovieTests(unittest.TestCase):
    def test_verified_snapshot_is_published_with_resumable_receipt(self):
        from dbscripts import backfill_movies as b
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            src = root / 'source/2023/05/02'
            src.mkdir(parents=True)
            png = src / 'ovro-lwa-352.synop_mfs_10s.2023-05-02T201603Z.image_I.png'
            make_png(png)
            frames = {'date': '2023-05-02', 'status': 'complete', 'source_manifest_sha256': 'b'*64, 'frames': [
                {'path': str(png), 'sha256': hashlib.sha256(png.read_bytes()).hexdigest(), 'observed':'2023-05-02T20:16:03'}]}
            manifest = root / 'day.json'
            manifest.write_text(json.dumps(frames))
            expected = hashlib.sha256(manifest.read_bytes()).hexdigest()
            result = b.process_day(manifest, expected, root/'work', root/'movies', root/'source', threads=1, expected_date='2023-05-02')
            self.assertEqual(result['status'], 'published')
            self.assertEqual(result['frames'], 1)
            self.assertEqual(result['sha256'], hashlib.sha256(pathlib.Path(result['path']).read_bytes()).hexdigest())
            again = b.process_day(manifest, expected, root/'work', root/'movies', root/'source', threads=1, expected_date='2023-05-02')
            self.assertEqual(again, result)
            self.assertEqual(json.loads(pathlib.Path(result['path']+'.backfill.json').read_text()), result)
    def test_batch_records_failure_without_touching_source(self):
        from dbscripts import backfill_movies as b
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            frames = root/'frames'
            frames.mkdir()
            p = frames/'2023-05-02.json'
            p.write_text(json.dumps({'date': '2023-05-02', 'status': 'complete', 'source_manifest_sha256': 'b'*64, 'frames': []}))
            summary = root/'summary.json'
            summary.write_text(json.dumps({'days': {'2023-05-02': {'manifest_sha256': hashlib.sha256(p.read_bytes()).hexdigest()}}}))
            rc = b.main(['--summary', str(summary), '--frames-dir', str(frames), '--work', str(root/'work'),
                         '--movies-root', str(root/'out'), '--source-root', str(root/'source'), '--jobs', '1'])
            self.assertEqual(rc, 1)
            state = json.loads((root/'work/status.json').read_text())
            self.assertEqual((state['total'], state['published'], state['failed']), (1, 0, 1))


if __name__ == '__main__':
    unittest.main()
