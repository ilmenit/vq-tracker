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


class TestSongDataSplit(unittest.TestCase):
    """Tests for song data split across two memory regions in banking mode.
    
    Banking mode layout:
      Region A: $8000-$CFFF (20,480 bytes) — metadata + patterns
      Region B: $D800-$FBFF ( 9,216 bytes) — overflow patterns
      Gap:      $D000-$D7FF (hardware I/O)
      Charset:  $FC00-$FFFF (relocated from $E000)
      Total:    29,696 bytes
    """

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.song_data_path = os.path.join(self.test_dir, "SONG_DATA.asm")
        self.song_data_2_path = os.path.join(self.test_dir, "SONG_DATA_2.asm")

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def _make_song_with_patterns(self, n_patterns, rows_per_pattern=64):
        """Create a song with many patterns containing events to generate data."""
        song = Song()
        song.patterns = []
        for i in range(n_patterns):
            p = Pattern(length=rows_per_pattern)
            # Add some events to generate real byte data
            for r in range(0, rows_per_pattern, 4):
                p.rows[r] = Row(note=25, instrument=1, volume=15)
            song.patterns.append(p)
        song.songlines = [Songline(patterns=[i % n_patterns for i in range(4)], speed=6)]
        # Ensure at least one instrument exists
        from data_model import Instrument
        while len(song.instruments) < 2:
            song.instruments.append(Instrument(name=f"inst{len(song.instruments)}"))
        return song

    def test_no_split_small_song(self):
        """Small song: everything fits in region A, SONG_DATA_2.asm is empty stub."""
        from build import export_song_data
        song = self._make_song_with_patterns(5)
        ok, err = export_song_data(song, self.song_data_path,
                                    region_a_limit=20480)
        self.assertTrue(ok, err)
        self.assertTrue(os.path.exists(self.song_data_path))
        self.assertTrue(os.path.exists(self.song_data_2_path))

        with open(self.song_data_path) as f:
            content = f.read()
        # All pattern labels should be in region A
        for i in range(5):
            self.assertIn(f"PTN_{i}:", content)
        self.assertIn("END OF SONG DATA", content)

        # Region B should be empty stub
        with open(self.song_data_2_path) as f:
            content2 = f.read()
        self.assertIn("no overflow", content2.lower())

    def test_split_large_song(self):
        """Large song: patterns overflow into SONG_DATA_2.asm (region B)."""
        from build import export_song_data
        # Create 100 patterns with events → should exceed a small region limit
        song = self._make_song_with_patterns(100, rows_per_pattern=64)
        # Use a deliberately small limit to force a split
        ok, err = export_song_data(song, self.song_data_path,
                                    region_a_limit=2000)
        self.assertTrue(ok, err)

        with open(self.song_data_path) as f:
            content_a = f.read()
        with open(self.song_data_2_path) as f:
            content_b = f.read()

        # Region A should have some patterns but not all
        self.assertIn("PTN_0:", content_a)
        self.assertNotIn("PTN_99:", content_a)
        # Region B should have the overflow patterns
        self.assertIn("PTN_99:", content_b)
        self.assertIn("END OF SONG DATA REGION B", content_b)
        # PATTERN_PTR_LO/HI should reference ALL patterns (labels resolved by assembler)
        for i in range(100):
            self.assertIn(f"<PTN_{i}", content_a)
            self.assertIn(f">PTN_{i}", content_a)

    def test_no_split_without_limit(self):
        """Without region_a_limit, no SONG_DATA_2.asm is generated."""
        from build import export_song_data
        song = self._make_song_with_patterns(10)
        ok, err = export_song_data(song, self.song_data_path,
                                    region_a_limit=0)
        self.assertTrue(ok, err)
        self.assertTrue(os.path.exists(self.song_data_path))
        self.assertFalse(os.path.exists(self.song_data_2_path))

    def test_region_size_constants(self):
        """Verify region size constants match the memory map."""
        region_a = 0xD000 - 0x8000   # $8000-$CFFF
        region_b = 0xFC00 - 0xD800   # $D800-$FBFF
        total = region_a + region_b

        self.assertEqual(region_a, 20480, "Region A must be 20,480 bytes")
        self.assertEqual(region_b, 9216, "Region B must be 9,216 bytes")
        self.assertEqual(total, 29696, "Total song budget must be 29,696 bytes")

        # Verify no overlap with I/O or charset
        self.assertLess(0x8000 + region_a, 0xD000 + 1,
                        "Region A must not reach I/O area")
        self.assertGreaterEqual(0xD800, 0xD000 + 0x800,
                        "Region B must start after I/O area")
        self.assertLess(0xD800 + region_b, 0xFC00 + 1,
                        "Region B must not reach charset at $FC00")

    def test_charset_relocation_address(self):
        """Charset at $FC00 must be 1KB-aligned for CHBASE."""
        charset_addr = 0xFC00
        chbase_val = charset_addr >> 8  # CHBASE is hi byte
        self.assertEqual(chbase_val, 0xFC)
        # CHBASE requires 1KB alignment (low 2 bits of page must be 0)
        self.assertEqual(charset_addr & 0x3FF, 0,
                        "Charset must be 1KB-aligned for ANTIC")
        # Character 127 (last char) overlaps vectors at $FFFA
        char127_start = charset_addr + 127 * 8
        char127_end = char127_start + 7
        self.assertEqual(char127_start, 0xFFF8,
                        "Char 127 starts at $FFF8")
        self.assertEqual(char127_end, 0xFFFF,
                        "Char 127 ends at $FFFF — overlaps vectors (acceptable)")
        # Characters 0-126 are fully intact
        char126_end = charset_addr + 126 * 8 + 7
        self.assertLess(char126_end, 0xFFFA,
                        "Characters 0-126 must not overlap vectors")


if __name__ == '__main__':
    unittest.main()
