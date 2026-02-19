"""Tests for MOD import speed tracking and Bxx/Dxx interaction."""

import struct
import unittest
import tempfile
import os


def _make_mod(n_samples=1, n_patterns=2, song_length=4,
              pattern_order=None, pattern_data=None):
    """Build a minimal valid MOD file in memory.
    
    Args:
        n_samples: Number of sample headers (up to 31).
        n_patterns: Number of pattern data blocks to include.
        song_length: Song length in positions.
        pattern_order: List of pattern indices (padded to 128).
        pattern_data: Dict of {pat_idx: {(row, ch): (sample, period, eff, param)}}.
    
    Returns:
        bytes: Complete MOD file.
    """
    if pattern_order is None:
        pattern_order = list(range(min(song_length, n_patterns)))
    while len(pattern_order) < 128:
        pattern_order.append(0)
    if pattern_data is None:
        pattern_data = {}
    
    buf = bytearray()
    
    # Title (20 bytes)
    buf += b'Test MOD\x00' + b'\x00' * 11
    
    # 31 sample headers (30 bytes each)
    for i in range(31):
        name = f'sample{i+1}'.encode('ascii')
        name = name[:22].ljust(22, b'\x00')
        buf += name
        if i < n_samples:
            length = 256  # 512 bytes sample data
            buf += struct.pack('>H', length)
            buf += bytes([0, 64])  # finetune=0, volume=64
            buf += struct.pack('>H', 0)  # rep_start
            buf += struct.pack('>H', 1)  # rep_len (1 word = no loop)
        else:
            buf += b'\x00' * 8
    
    # Song length + restart
    buf += bytes([song_length, 127])
    
    # Pattern order table (128 bytes)
    buf += bytes(pattern_order[:128])
    
    # Signature
    buf += b'M.K.'
    
    # Pattern data (64 rows × 4 channels × 4 bytes)
    for pat_idx in range(n_patterns):
        for row in range(64):
            for ch in range(4):
                cell = pattern_data.get(pat_idx, {}).get((row, ch))
                if cell:
                    sample, period, eff, param = cell
                    b0 = (sample & 0xF0) | ((period >> 8) & 0x0F)
                    b1 = period & 0xFF
                    b2 = ((sample & 0x0F) << 4) | (eff & 0x0F)
                    b3 = param & 0xFF
                    buf += bytes([b0, b1, b2, b3])
                else:
                    buf += b'\x00\x00\x00\x00'
    
    # Sample data (silence)
    for i in range(n_samples):
        buf += b'\x80' * 512
    
    return bytes(buf)


class TestModImportSpeed(unittest.TestCase):
    """Test that speed commands are tracked through ALL rows, not just row 0."""
    
    def _import_mod(self, mod_data, options=None):
        """Write MOD to temp file, import it, return Song."""
        from mod_import import import_mod_file
        fd, path = tempfile.mkstemp(suffix='.mod')
        try:
            with os.fdopen(fd, 'wb') as f:
                f.write(mod_data)
            opts = {'volume_control': False, 'dedup_patterns': False}
            if options:
                opts.update(options)
            song, log = import_mod_file(path, options=opts)
            return song, log
        finally:
            os.unlink(path)
    
    def test_speed_carry_forward_from_mid_pattern(self):
        """Speed set mid-pattern should carry to next songline.
        
        Pattern 0: F01 on row 0, F04 on row 8.
        Pattern 1: no speed commands.
        
        Old bug: songline 1 inherited speed=1 from pattern 0 row 0.
        Fix: songline 1 should inherit speed=4 (last speed in pattern 0).
        """
        pdata = {
            0: {
                (0, 3): (0, 0, 0xF, 1),   # F01 speed=1 on row 0
                (8, 2): (0, 0, 0xF, 4),   # F04 speed=4 on row 8
            },
            1: {},  # No speed commands
        }
        mod = _make_mod(n_patterns=2, song_length=2,
                        pattern_order=[0, 1], pattern_data=pdata)
        song, log = self._import_mod(mod)
        
        self.assertIsNotNone(song)
        self.assertEqual(len(song.songlines), 2)
        # Songline 0: last speed in pattern 0 is 4
        self.assertEqual(song.songlines[0].speed, 4)
        # Songline 1: carries forward speed=4 from pattern 0
        self.assertEqual(song.songlines[1].speed, 4)
    
    def test_speed_1_timing_trick(self):
        """Speed=1 on row 0 followed by real speed on row 1.
        
        This is a common MOD technique. The imported songline should
        get the dominant speed (last in pattern), not speed=1.
        """
        pdata = {
            0: {
                (0, 3): (0, 0, 0xF, 1),    # F01 speed=1 (timing trick)
                (1, 3): (0, 0, 0xF, 10),   # F0A speed=10 (real speed)
                (8, 2): (0, 0, 0xF, 4),    # F04 speed=4 (section change)
            },
        }
        mod = _make_mod(n_patterns=3, song_length=3,
                        pattern_order=[0, 1, 2], pattern_data=pdata)
        song, log = self._import_mod(mod)
        
        self.assertIsNotNone(song)
        # Songline 0: last speed in pattern 0 is 4
        self.assertEqual(song.songlines[0].speed, 4)
        # Song initial speed should be 4 (last speed, not 1)
        self.assertEqual(song.speed, 4)
    
    def test_speed_default_without_fxx(self):
        """Patterns without Fxx should use default speed=6."""
        pdata = {0: {}, 1: {}}
        mod = _make_mod(n_patterns=2, song_length=2,
                        pattern_order=[0, 1], pattern_data=pdata)
        song, log = self._import_mod(mod)
        
        self.assertIsNotNone(song)
        self.assertEqual(song.songlines[0].speed, 6)
        self.assertEqual(song.songlines[1].speed, 6)


class TestModImportBxxDxx(unittest.TestCase):
    """Test Bxx (Position Jump) and Dxx (Pattern Break) interaction."""
    
    def _import_mod(self, mod_data, options=None):
        from mod_import import import_mod_file
        fd, path = tempfile.mkstemp(suffix='.mod')
        try:
            with os.fdopen(fd, 'wb') as f:
                f.write(mod_data)
            opts = {'volume_control': False, 'dedup_patterns': False}
            if options:
                opts.update(options)
            song, log = import_mod_file(path, options=opts)
            return song, log
        finally:
            os.unlink(path)
    
    def test_bxx_backward_truncates_song(self):
        """Backward Bxx should truncate song at that position."""
        pdata = {
            1: {
                (63, 1): (0, 0, 0xB, 0),  # B00 = jump to pos 0
            },
        }
        mod = _make_mod(n_patterns=3, song_length=4,
                        pattern_order=[0, 1, 2, 0], pattern_data=pdata)
        song, log = self._import_mod(mod)
        
        self.assertIsNotNone(song)
        # Position 1 has B00 (backward to 0) → song ends at pos 1
        self.assertEqual(len(song.songlines), 2)  # pos 0 and 1
    
    def test_dxx_before_bxx_blocks_truncation(self):
        """Dxx on earlier row should prevent Bxx from truncating.
        
        Pattern has Dxx on row 20 and Bxx on row 30.
        Dxx fires first → pattern ends at row 20 → Bxx never executes.
        Song should NOT be truncated.
        """
        pdata = {
            1: {
                (20, 2): (0, 0, 0xD, 0),   # D00 = pattern break (row 20)
                (30, 1): (0, 0, 0xB, 0),   # B00 = jump to pos 0 (row 30)
            },
        }
        mod = _make_mod(n_patterns=3, song_length=4,
                        pattern_order=[0, 1, 2, 0], pattern_data=pdata)
        song, log = self._import_mod(mod)
        
        self.assertIsNotNone(song)
        # Dxx at row 20 blocks Bxx at row 30 → no truncation
        self.assertEqual(len(song.songlines), 4)
    
    def test_bxx_forward_no_truncation(self):
        """Forward Bxx (jumping to later position) should not truncate."""
        pdata = {
            0: {
                (0, 0): (0, 0, 0xB, 3),  # B03 = jump to pos 3 (forward)
            },
        }
        mod = _make_mod(n_patterns=4, song_length=4,
                        pattern_order=[0, 1, 2, 3], pattern_data=pdata)
        song, log = self._import_mod(mod)
        
        self.assertIsNotNone(song)
        self.assertEqual(len(song.songlines), 4)


if __name__ == '__main__':
    unittest.main()
