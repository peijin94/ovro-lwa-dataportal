import importlib.util
import pathlib
import tempfile
import unittest
import struct
import zlib
import json
import subprocess
from datetime import datetime


def make_png(path, rgb=(255, 0, 0), width=17, height=15):
    def chunk(kind, data):
        return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data))
    path.write_bytes(b'\x89PNG\r\n\x1a\n' +
                     chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0)) +
                     chunk(b'IDAT', zlib.compress((b'\0' + bytes(rgb) * width) * height)) +
                     chunk(b'IEND', b''))

ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('daily_movie', ROOT / 'dbscripts/generate_daily_movie.py')
assert spec is not None and spec.loader is not None
movie = importlib.util.module_from_spec(spec)
spec.loader.exec_module(movie)


class MovieTests(unittest.TestCase):
    def test_mixed_prefix_frames_are_sorted_by_time_and_only_mfs_i(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = pathlib.Path(tmp) / '2024/01/11'
            d.mkdir(parents=True)
            names = ['ovro-lwa-352.synop_mfs_10s.2024-01-11T170000Z.image_I.png',
                     'ovro-lwa.lev1_mfs_10s.2024-01-11T160000Z.png',
                     'ovro-lwa.synop_mfs_10s.2024-01-11T180000Z.image_I.png',
                     'ovro-lwa-352.synop_mfs_10s.2024-01-11T150000Z.image_V.png',
                     'ovro-lwa-352.synop_fch_10s.2024-01-11T140000Z.image_I.png']
            for name in names:
                (d / name).touch()
            actual = movie._pngs_for_daily_window(datetime(2024, 1, 11), tmp)
            self.assertEqual([pathlib.Path(p).name for p in actual], [names[1], names[0], names[2]])
    def test_explicit_frames_regenerate_and_validate_movie(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            frames = []
            for n, color in enumerate([(255, 0, 0), (0, 255, 0), (0, 0, 255)]):
                p = root / f'ovro-lwa.lev1_mfs_10s.2024-01-11T00000{n}Z.png'
                make_png(p, color)
                frames.append(str(p))
            out = pathlib.Path(movie._movie_path(datetime(2024, 1, 11), str(root / 'out')))
            out.parent.mkdir(parents=True)
            out.write_bytes(b'old movie retained until encode succeeds')
            self.assertTrue(movie.generate_daily_movie(datetime(2024, 1, 11), '', str(root / 'out'), 2,
                                                      frames=frames[::-1], overwrite=True, threads=1))
            info = json.loads(subprocess.check_output(['ffprobe', '-v', 'error', '-show_streams', '-of', 'json', str(out)]))['streams'][0]
            self.assertEqual(int(info['nb_frames']), 3)
            self.assertEqual((info['codec_name'], info['pix_fmt'], info['width'], info['height']), ('h264', 'yuv420p', 18, 16))
            self.assertFalse(list(out.parent.glob('*.tmp.mp4')))
    def test_explicit_frames_reject_ambiguous_or_non_i_inputs_before_encoding(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            names = ['ovro-lwa.lev1_fch_10s.2024-01-11T000001Z.image_I.png',
                     'ovro-lwa.lev1_mfs_10s.2024-01-11T000001Z.image_V.png',
                     'ovro-lwa.lev1_mfs_10s.2024-01-11T000001Z.image_I.png',
                     'ovro-lwa-352.synop_mfs_10s.2024-01-11T000001Z.image_I.png']
            for n in names:
                make_png(root / n)
            for selected in [[names[0]], [names[1]], names[2:]]:
                with self.subTest(selected=selected):
                    with self.assertRaises(ValueError):
                        movie.generate_daily_movie(datetime(2024, 1, 11), '', str(root/'out'), 6,
                                                   frames=[str(root/n) for n in selected])
    def test_dimension_changes_do_not_replace_a_previous_movie(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            a = root / 'ovro-lwa.lev1_mfs_10s.2024-01-11T000001Z.png'
            b = root / 'ovro-lwa.lev1_mfs_10s.2024-01-11T000002Z.png'
            make_png(a, width=17)
            make_png(b, width=31)
            out = pathlib.Path(movie._movie_path(datetime(2024, 1, 11), str(root/'out')))
            out.parent.mkdir(parents=True)
            out.write_bytes(b'previous valid artifact')
            with self.assertRaises(ValueError):
                movie.generate_daily_movie(datetime(2024, 1, 11), '', str(root/'out'), 6,
                                           frames=[str(a), str(b)], overwrite=True)
            self.assertEqual(out.read_bytes(), b'previous valid artifact')
    def test_legacy_discovery_retains_alias_frames_without_breaking_cron(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=pathlib.Path(tmp)
            src=root/'source/2024/01/11'; src.mkdir(parents=True)
            for prefix in ['ovro-lwa-352.synop', 'ovro-lwa.lev1']:
                make_png(src/(prefix+'_mfs_10s.2024-01-11T160000Z.image_I.png'))
            self.assertTrue(movie.generate_daily_movie(datetime(2024,1,11),str(root/'source'),str(root/'out'),6))
            output=movie._movie_path(datetime(2024,1,11),str(root/'out'))
            self.assertEqual(int(movie.validate_movie(output,2)['nb_frames']),2)
            self.assertTrue(movie.generate_daily_movie(datetime(2024,1,11),str(root/'source'),str(root/'out'),6))


if __name__ == '__main__':
    unittest.main()
