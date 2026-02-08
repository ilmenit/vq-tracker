"""Tests for export functionality - ASM and binary export.

Covers:
- ASM export format correctness
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
from file_io import export_asm, export_binary


class TestAsmExport(unittest.TestCase):
    """Tests for ASM export."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_basic_export(self):
        song = Song(title="Test", author="Tester")
        ok, msg = export_asm(song, self.test_dir)
        self.assertTrue(ok)
        
        asm_path = os.path.join(self.test_dir, "SONG_DATA.asm")
        self.assertTrue(os.path.exists(asm_path))
        
        with open(asm_path, 'r') as f:
            content = f.read()
        
        self.assertIn("Test", content)
        self.assertIn("Tester", content)
        self.assertIn("SONG_LENGTH", content)
        self.assertIn("PATTERN_COUNT", content)

    def test_note_off_export(self):
        """NOTE_OFF should be exported as note=0 in ASM."""
        song = Song()
        song.patterns[0].rows[0].note = NOTE_OFF
        song.patterns[0].rows[0].instrument = 0
        song.patterns[0].rows[0].volume = 15
        
        ok, _ = export_asm(song, self.test_dir)
        self.assertTrue(ok)
        
        with open(os.path.join(self.test_dir, "SONG_DATA.asm"), 'r') as f:
            content = f.read()
        
        # NOTE_OFF (255) should become 0 with high bit set = $80
        self.assertIn("$80", content)

    def test_pattern_end_marker(self):
        """Each pattern should end with $FF marker."""
        song = Song()
        ok, _ = export_asm(song, self.test_dir)
        self.assertTrue(ok)
        
        with open(os.path.join(self.test_dir, "SONG_DATA.asm"), 'r') as f:
            content = f.read()
        
        self.assertIn("$FF", content)

    def test_speed_per_songline(self):
        """Each songline should have its own speed."""
        song = Song()
        song.songlines[0].speed = 3
        song.songlines.append(Songline(speed=8))
        
        ok, _ = export_asm(song, self.test_dir)
        self.assertTrue(ok)
        
        with open(os.path.join(self.test_dir, "SONG_DATA.asm"), 'r') as f:
            content = f.read()
        
        self.assertIn("SONG_SPEED", content)
        self.assertIn("$03", content)
        self.assertIn("$08", content)


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
