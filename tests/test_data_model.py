"""Tests for data_model.py - Row, Pattern, Instrument, Songline, Song.

Covers:
- Construction and defaults
- Serialization round-trips (to_dict → from_dict)
- Boundary value handling
- Operations (clear, copy, transpose, insert, delete)
"""
import sys
import os
import unittest

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from constants import (MAX_VOLUME, MAX_NOTES, MAX_INSTRUMENTS, MAX_CHANNELS,
                       NOTE_OFF, DEFAULT_LENGTH, DEFAULT_SPEED, PAL_HZ)
from data_model import Row, Pattern, Instrument, Songline, Song


class TestRow(unittest.TestCase):
    """Tests for Row dataclass."""

    def test_defaults(self):
        r = Row()
        self.assertEqual(r.note, 0)
        self.assertEqual(r.instrument, 0)
        self.assertEqual(r.volume, MAX_VOLUME)

    def test_construction(self):
        r = Row(note=12, instrument=3, volume=8)
        self.assertEqual(r.note, 12)
        self.assertEqual(r.instrument, 3)
        self.assertEqual(r.volume, 8)

    def test_clear(self):
        r = Row(note=12, instrument=3, volume=8)
        r.clear()
        self.assertEqual(r.note, 0)
        self.assertEqual(r.instrument, 0)
        self.assertEqual(r.volume, MAX_VOLUME)

    def test_copy(self):
        r = Row(note=24, instrument=5, volume=10)
        c = r.copy()
        self.assertEqual(c.note, 24)
        self.assertEqual(c.instrument, 5)
        self.assertEqual(c.volume, 10)
        # Ensure it's a true copy
        c.note = 1
        self.assertEqual(r.note, 24)

    def test_serialization_roundtrip(self):
        r = Row(note=36, instrument=127, volume=15)
        d = r.to_dict()
        r2 = Row.from_dict(d)
        self.assertEqual(r2.note, 36)
        self.assertEqual(r2.instrument, 127)
        self.assertEqual(r2.volume, 15)

    def test_serialization_empty(self):
        r = Row()
        d = r.to_dict()
        r2 = Row.from_dict(d)
        self.assertEqual(r2.note, 0)
        self.assertEqual(r2.instrument, 0)
        self.assertEqual(r2.volume, MAX_VOLUME)

    def test_from_dict_missing_keys(self):
        """Missing keys should use defaults."""
        r = Row.from_dict({})
        self.assertEqual(r.note, 0)
        self.assertEqual(r.instrument, 0)
        self.assertEqual(r.volume, MAX_VOLUME)

    def test_from_dict_clamping(self):
        """Out-of-range values should be clamped."""
        r = Row.from_dict({'n': 999, 'i': 999, 'v': 999})
        self.assertEqual(r.note, MAX_NOTES)
        self.assertEqual(r.instrument, MAX_INSTRUMENTS - 1)
        self.assertEqual(r.volume, MAX_VOLUME)

    def test_from_dict_negative_clamping(self):
        r = Row.from_dict({'n': -5, 'i': -1, 'v': -1})
        self.assertEqual(r.note, 0)
        self.assertEqual(r.instrument, 0)
        self.assertEqual(r.volume, 0)

    def test_note_off_preserved(self):
        """NOTE_OFF (255) must pass through clamping."""
        r = Row.from_dict({'n': NOTE_OFF})
        self.assertEqual(r.note, NOTE_OFF)


class TestPattern(unittest.TestCase):
    """Tests for Pattern dataclass."""

    def test_defaults(self):
        p = Pattern()
        self.assertEqual(p.length, DEFAULT_LENGTH)
        self.assertEqual(len(p.rows), DEFAULT_LENGTH)

    def test_custom_length(self):
        p = Pattern(length=16)
        self.assertEqual(p.length, 16)
        self.assertEqual(len(p.rows), 16)

    def test_get_row(self):
        p = Pattern(length=4)
        p.rows[2].note = 12
        self.assertEqual(p.get_row(2).note, 12)
        # Out of bounds returns empty row
        self.assertEqual(p.get_row(100).note, 0)

    def test_set_length_grow(self):
        p = Pattern(length=4)
        p.set_length(8)
        self.assertEqual(p.length, 8)
        self.assertEqual(len(p.rows), 8)

    def test_set_length_shrink(self):
        p = Pattern(length=8)
        p.rows[6].note = 12
        p.set_length(4)
        self.assertEqual(p.length, 4)
        self.assertEqual(len(p.rows), 4)

    def test_insert_row(self):
        p = Pattern(length=4)
        p.rows[0].note = 1
        p.rows[1].note = 2
        p.rows[2].note = 3
        p.rows[3].note = 4
        p.insert_row(1)
        self.assertEqual(p.rows[0].note, 1)
        self.assertEqual(p.rows[1].note, 0)  # Inserted
        self.assertEqual(p.rows[2].note, 2)
        self.assertEqual(p.rows[3].note, 3)
        # Row 4 was pushed out

    def test_delete_row(self):
        p = Pattern(length=4)
        p.rows[0].note = 1
        p.rows[1].note = 2
        p.rows[2].note = 3
        p.delete_row(1)
        self.assertEqual(p.rows[0].note, 1)
        self.assertEqual(p.rows[1].note, 3)
        self.assertEqual(p.rows[3].note, 0)  # New empty row at end

    def test_clear(self):
        p = Pattern(length=4)
        for r in p.rows:
            r.note = 12
        p.clear()
        for r in p.rows:
            self.assertEqual(r.note, 0)

    def test_transpose(self):
        p = Pattern(length=4)
        p.rows[0].note = 1
        p.rows[1].note = 12
        p.rows[2].note = 0  # Empty - should stay 0
        p.rows[3].note = MAX_NOTES
        p.transpose(2)
        self.assertEqual(p.rows[0].note, 3)
        self.assertEqual(p.rows[1].note, 14)
        self.assertEqual(p.rows[2].note, 0)  # Empty unchanged
        self.assertEqual(p.rows[3].note, MAX_NOTES)  # Clamped

    def test_copy(self):
        p = Pattern(length=4)
        p.rows[0].note = 24
        c = p.copy()
        self.assertEqual(c.rows[0].note, 24)
        c.rows[0].note = 1
        self.assertEqual(p.rows[0].note, 24)  # Original unchanged

    def test_serialization_roundtrip(self):
        p = Pattern(length=8)
        p.rows[0].note = 12
        p.rows[0].instrument = 3
        p.rows[0].volume = 10
        p.rows[4].note = 24
        d = p.to_dict()
        p2 = Pattern.from_dict(d)
        self.assertEqual(p2.length, 8)
        self.assertEqual(p2.rows[0].note, 12)
        self.assertEqual(p2.rows[0].instrument, 3)
        self.assertEqual(p2.rows[0].volume, 10)
        self.assertEqual(p2.rows[4].note, 24)

    def test_serialization_empty(self):
        p = Pattern.from_dict({})
        self.assertEqual(p.length, DEFAULT_LENGTH)


class TestInstrument(unittest.TestCase):
    """Tests for Instrument dataclass."""

    def test_defaults(self):
        i = Instrument()
        self.assertEqual(i.name, "New")
        self.assertEqual(i.sample_path, "")
        self.assertEqual(i.base_note, 1)
        self.assertFalse(i.is_loaded())

    def test_serialization_roundtrip(self):
        i = Instrument(name="Bass", sample_path="/tmp/bass.wav",
                       base_note=13, sample_rate=22050)
        d = i.to_dict()
        i2 = Instrument.from_dict(d)
        self.assertEqual(i2.name, "Bass")
        # sample_path is persisted (needed by undo system for audio re-attachment)
        self.assertEqual(i2.sample_path, "/tmp/bass.wav")
        self.assertEqual(i2.base_note, 13)
        self.assertEqual(i2.sample_rate, 22050)
        self.assertIsNone(i2.sample_data)  # Audio not serialized

    def test_from_dict_missing_keys(self):
        i = Instrument.from_dict({})
        self.assertEqual(i.name, "New")
        self.assertEqual(i.base_note, 1)


class TestSongline(unittest.TestCase):
    """Tests for Songline dataclass."""

    def test_defaults(self):
        sl = Songline()
        self.assertEqual(len(sl.patterns), MAX_CHANNELS)
        self.assertEqual(sl.speed, DEFAULT_SPEED)

    def test_copy(self):
        sl = Songline(patterns=[5, 6, 7, 8], speed=8)
        c = sl.copy()
        self.assertEqual(c.patterns, [5, 6, 7, 8])
        self.assertEqual(c.speed, 8)
        c.patterns[0] = 99
        self.assertEqual(sl.patterns[0], 5)  # Original unchanged


class TestSong(unittest.TestCase):
    """Tests for Song dataclass."""

    def test_defaults(self):
        s = Song()
        self.assertEqual(s.title, "Untitled")
        self.assertGreaterEqual(len(s.songlines), 1)
        self.assertGreaterEqual(len(s.patterns), MAX_CHANNELS)

    def test_reset(self):
        s = Song(title="Test", author="Me")
        s.instruments.append(Instrument(name="Bass"))
        s.reset()
        self.assertEqual(s.title, "Untitled")
        self.assertEqual(s.author, "")
        self.assertEqual(len(s.instruments), 0)
        self.assertFalse(s.modified)

    def test_serialization_roundtrip(self):
        """Full Song round-trip serialization."""
        s = Song(title="Test Song", author="Tester", speed=8)
        s.volume_control = True
        s.screen_control = False

        # Add some patterns with data
        s.patterns[0].rows[0].note = 12
        s.patterns[0].rows[0].instrument = 1

        # Add songlines
        s.songlines.append(Songline(patterns=[1, 2, 0, 3], speed=4))

        # Add instruments
        s.instruments.append(Instrument(name="Kick", base_note=1))
        s.instruments.append(Instrument(name="Snare", base_note=13))

        d = s.to_dict()
        s2 = Song.from_dict(d)

        self.assertEqual(s2.title, "Test Song")
        self.assertEqual(s2.author, "Tester")
        self.assertTrue(s2.volume_control)
        self.assertFalse(s2.screen_control)
        self.assertEqual(s2.patterns[0].rows[0].note, 12)
        self.assertEqual(s2.patterns[0].rows[0].instrument, 1)
        self.assertEqual(len(s2.songlines), 2)
        self.assertEqual(s2.songlines[1].patterns, [1, 2, 0, 3])
        self.assertEqual(s2.songlines[1].speed, 4)
        self.assertEqual(len(s2.instruments), 2)
        self.assertEqual(s2.instruments[0].name, "Kick")
        self.assertEqual(s2.instruments[1].name, "Snare")

    def test_add_delete_pattern(self):
        s = Song()
        initial = len(s.patterns)
        idx = s.add_pattern()
        self.assertEqual(len(s.patterns), initial + 1)
        self.assertEqual(idx, initial)
        # Can't delete pattern in use
        self.assertFalse(s.delete_pattern(0))
        # Can delete unused pattern
        self.assertTrue(s.delete_pattern(idx))

    def test_add_delete_songline(self):
        s = Song()
        self.assertEqual(len(s.songlines), 1)
        idx = s.add_songline()
        self.assertEqual(len(s.songlines), 2)
        self.assertTrue(s.delete_songline(idx))
        self.assertEqual(len(s.songlines), 1)
        # Can't delete last songline
        self.assertFalse(s.delete_songline(0))

    def test_add_instrument(self):
        s = Song()
        idx = s.add_instrument("Bass")
        self.assertEqual(idx, 0)
        self.assertEqual(s.instruments[0].name, "Bass")

    def test_pattern_in_use(self):
        s = Song()
        self.assertTrue(s.pattern_in_use(0))
        s.add_pattern()
        self.assertFalse(s.pattern_in_use(len(s.patterns) - 1))


class TestSongSerializationEdgeCases(unittest.TestCase):
    """Edge cases in serialization."""

    def test_empty_dict(self):
        s = Song.from_dict({})
        self.assertEqual(s.title, "Untitled")
        self.assertGreaterEqual(len(s.patterns), MAX_CHANNELS)
        self.assertGreaterEqual(len(s.songlines), 1)

    def test_note_off_survives_roundtrip(self):
        s = Song()
        s.patterns[0].rows[0].note = NOTE_OFF
        d = s.to_dict()
        s2 = Song.from_dict(d)
        self.assertEqual(s2.patterns[0].rows[0].note, NOTE_OFF)

    def test_all_max_values(self):
        """Test with maximum valid values."""
        r = Row(note=MAX_NOTES, instrument=MAX_INSTRUMENTS - 1, volume=MAX_VOLUME)
        d = r.to_dict()
        r2 = Row.from_dict(d)
        self.assertEqual(r2.note, MAX_NOTES)
        self.assertEqual(r2.instrument, MAX_INSTRUMENTS - 1)
        self.assertEqual(r2.volume, MAX_VOLUME)

    def test_backward_compat_3ch_song(self):
        """Old 3-channel song files load into 4-channel tracker."""
        old_dict = {
            'version': 1,
            'meta': {'title': 'Old Song'},
            'songlines': [
                {'patterns': [0, 1, 2], 'speed': 6},
            ],
            'patterns': [
                {'length': 16, 'rows': []},
                {'length': 32, 'rows': []},
                {'length': 64, 'rows': []},
            ],
            'instruments': [],
        }
        song = Song.from_dict(old_dict)
        # 3-element pattern list padded to 4
        self.assertEqual(len(song.songlines[0].patterns), MAX_CHANNELS)
        self.assertEqual(song.songlines[0].patterns, [0, 1, 2, 0])
        # Minimum 4 patterns created
        self.assertGreaterEqual(len(song.patterns), MAX_CHANNELS)


if __name__ == '__main__':
    unittest.main()
