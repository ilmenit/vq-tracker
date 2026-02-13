"""Tests for binary export functionality.

Covers:
- Binary export format
- NOTE_OFF handling in export
- Variable-length event encoding
"""
import sys
import os
import tempfile
import shutil
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from constants import NOTE_OFF
from data_model import Song, Pattern, Row, Songline
from file_io import export_binary


class TestBinaryExport(unittest.TestCase):
    """Tests for binary .pvg export."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_basic_export(self):
        song = Song()
        path = os.path.join(self.test_dir, "test.pvg")
        ok, msg = export_binary(song, path)
        self.assertTrue(ok)
        self.assertTrue(os.path.exists(path))
        
        with open(path, 'rb') as f:
            magic = f.read(3)
            self.assertEqual(magic, b'PVG')

    def test_auto_extension(self):
        song = Song()
        path = os.path.join(self.test_dir, "noext")
        ok, _ = export_binary(song, path)
        self.assertTrue(ok)
        self.assertTrue(os.path.exists(path + ".pvg"))

    def test_pvg_v4_header(self):
        """Version 4 header: magic + ver(4) + channels(MAX) + speed + system."""
        import struct
        from constants import MAX_CHANNELS, PAL_HZ

        song = Song()
        song.songlines[0].speed = 5
        path = os.path.join(self.test_dir, "v4.pvg")
        ok, _ = export_binary(song, path)
        self.assertTrue(ok)

        with open(path, 'rb') as f:
            magic = f.read(3)
            self.assertEqual(magic, b'PVG')
            version = struct.unpack('B', f.read(1))[0]
            self.assertEqual(version, 4)
            channels = struct.unpack('B', f.read(1))[0]
            self.assertEqual(channels, MAX_CHANNELS)
            speed = struct.unpack('<B', f.read(1))[0]
            self.assertEqual(speed, 5)

    def test_pvg_v4_per_songline_speed(self):
        """Each songline must write its own speed byte after pattern bytes."""
        import struct
        from constants import MAX_CHANNELS

        song = Song()
        song.songlines[0].speed = 3
        song.songlines.append(Songline(patterns=[0, 0, 0, 0], speed=9))

        path = os.path.join(self.test_dir, "speed.pvg")
        ok, _ = export_binary(song, path)
        self.assertTrue(ok)

        with open(path, 'rb') as f:
            # Skip header: magic(3) + ver(1) + ch(1) + speed(1) + sys(1) + sl_count(2) + ptn_count(2) + inst_count(1) = 12 bytes
            f.read(12)
            # Songline 0: MAX_CHANNELS pattern bytes + 1 speed byte
            ptn_bytes_0 = struct.unpack(f'{MAX_CHANNELS}B', f.read(MAX_CHANNELS))
            speed_0 = struct.unpack('B', f.read(1))[0]
            self.assertEqual(speed_0, 3)
            # Songline 1: MAX_CHANNELS pattern bytes + 1 speed byte
            ptn_bytes_1 = struct.unpack(f'{MAX_CHANNELS}B', f.read(MAX_CHANNELS))
            speed_1 = struct.unpack('B', f.read(1))[0]
            self.assertEqual(speed_1, 9)

    def test_pvg_v4_songline_patterns(self):
        """Songline pattern bytes written correctly for 4 channels."""
        import struct
        from constants import MAX_CHANNELS

        song = Song()
        # Need enough patterns
        while len(song.patterns) < 6:
            song.add_pattern()
        song.songlines[0] = Songline(patterns=[0, 2, 4, 5], speed=6)

        path = os.path.join(self.test_dir, "ptn.pvg")
        ok, _ = export_binary(song, path)
        self.assertTrue(ok)

        with open(path, 'rb') as f:
            f.read(12)  # Skip header
            ptn_bytes = struct.unpack(f'{MAX_CHANNELS}B', f.read(MAX_CHANNELS))
            self.assertEqual(ptn_bytes, (0, 2, 4, 5))


if __name__ == '__main__':
    unittest.main()
