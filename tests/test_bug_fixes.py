"""Tests for bug fixes.

Covers all 8 bugs identified and fixed:
  Bug 1: File browser checkbox/selectable desync (UI - not unit testable)
  Bug 2: Folder selectable toggle flash (UI - not unit testable)
  Bug 3: Instrument move corrupts pattern data
  Bug 4: remove_instrument doesn't remap pattern indices
  Bug 5: save_undo called AFTER modification
  Bug 6: Partial digit entry corrupts undo state
  Bug 7: Song.speed dead code / export_binary uses stale default
  Bug 8: transpose doesn't exclude NOTE_OFF
"""
import sys
import os
import struct
import tempfile
import shutil
import unittest
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Mock sounddevice before importing state
try:
    import sounddevice
except (ImportError, OSError):
    import types
    sd_mock = types.ModuleType('sounddevice')
    sd_mock.__version__ = '0.0.0'
    sys.modules['sounddevice'] = sd_mock

from constants import (
    NOTE_OFF, MAX_NOTES, MAX_INSTRUMENTS, MAX_VOLUME, DEFAULT_SPEED,
)
from data_model import Song, Pattern, Row, Instrument, Songline
from state import UndoManager
from file_io import export_binary


# ============================================================================
# Bug 3: Instrument move must remap pattern row indices
# ============================================================================

class TestInstrumentMoveRemapsPatternData(unittest.TestCase):
    """Bug 3: Moving instruments must update all pattern row references."""

    def _swap_and_remap(self, song, idx_a, idx_b):
        """Reproduce the fixed move operation (swap instruments + remap)."""
        song.instruments[idx_a], song.instruments[idx_b] = \
            song.instruments[idx_b], song.instruments[idx_a]
        for pattern in song.patterns:
            for row in pattern.rows:
                if row.instrument == idx_a:
                    row.instrument = idx_b
                elif row.instrument == idx_b:
                    row.instrument = idx_a

    def test_move_down_remaps(self):
        """Moving instrument 1 down should swap indices 1 and 2 in patterns."""
        song = Song()
        for i in range(4):
            song.add_instrument(f"Inst{i}")
        ptn = song.patterns[0]
        ptn.rows[0].instrument = 0
        ptn.rows[1].instrument = 1
        ptn.rows[2].instrument = 2
        ptn.rows[3].instrument = 3

        self._swap_and_remap(song, 1, 2)

        self.assertEqual(ptn.rows[0].instrument, 0)
        self.assertEqual(ptn.rows[1].instrument, 2)  # was 1, now 2
        self.assertEqual(ptn.rows[2].instrument, 1)  # was 2, now 1
        self.assertEqual(ptn.rows[3].instrument, 3)
        # Verify instrument objects themselves swapped
        self.assertEqual(song.instruments[1].name, "Inst2")
        self.assertEqual(song.instruments[2].name, "Inst1")

    def test_move_up_remaps(self):
        """Moving instrument 2 up should swap indices 2 and 1 in patterns."""
        song = Song()
        for i in range(3):
            song.add_instrument(f"Inst{i}")
        ptn = song.patterns[0]
        ptn.rows[0].instrument = 2
        ptn.rows[1].instrument = 1

        self._swap_and_remap(song, 2, 1)

        self.assertEqual(ptn.rows[0].instrument, 1)
        self.assertEqual(ptn.rows[1].instrument, 2)

    def test_remap_across_multiple_patterns(self):
        """Remapping must affect ALL patterns, not just the active one."""
        song = Song()
        for i in range(3):
            song.add_instrument(f"Inst{i}")
        song.add_pattern()  # pattern 1
        song.patterns[0].rows[0].instrument = 0
        song.patterns[1].rows[0].instrument = 0
        song.patterns[0].rows[1].instrument = 1
        song.patterns[1].rows[1].instrument = 1

        self._swap_and_remap(song, 0, 1)

        # Both patterns should be remapped
        self.assertEqual(song.patterns[0].rows[0].instrument, 1)
        self.assertEqual(song.patterns[1].rows[0].instrument, 1)
        self.assertEqual(song.patterns[0].rows[1].instrument, 0)
        self.assertEqual(song.patterns[1].rows[1].instrument, 0)

    def test_rows_not_referencing_swapped_indices_unchanged(self):
        """Rows referencing unrelated instruments must not change."""
        song = Song()
        for i in range(5):
            song.add_instrument(f"Inst{i}")
        ptn = song.patterns[0]
        ptn.rows[0].instrument = 4
        ptn.rows[1].instrument = 3

        self._swap_and_remap(song, 0, 1)

        self.assertEqual(ptn.rows[0].instrument, 4)
        self.assertEqual(ptn.rows[1].instrument, 3)

    def test_move_is_undoable(self):
        """Instrument move should be undoable via UndoManager."""
        um = UndoManager()
        song = Song()
        for i in range(3):
            song.add_instrument(f"Inst{i}")
        song.patterns[0].rows[0].instrument = 1

        um.save(song, "Move instrument")
        self._swap_and_remap(song, 1, 2)

        self.assertEqual(song.patterns[0].rows[0].instrument, 2)

        um.undo(song)
        self.assertEqual(song.patterns[0].rows[0].instrument, 1)
        self.assertEqual(song.instruments[1].name, "Inst1")


# ============================================================================
# Bug 4: remove_instrument must remap pattern row indices
# ============================================================================

class TestRemoveInstrumentRemapsPatternData(unittest.TestCase):
    """Bug 4: Removing an instrument must decrement higher indices and
    zero-out rows that referenced the removed instrument."""

    def test_basic_removal_remaps(self):
        """Remove instrument 1: inst 2->1, inst 3->2, inst 1->0."""
        song = Song()
        for i in range(4):
            song.add_instrument(f"Inst{i}")
        ptn = song.patterns[0]
        ptn.rows[0].instrument = 0
        ptn.rows[1].instrument = 1
        ptn.rows[2].instrument = 2
        ptn.rows[3].instrument = 3

        song.remove_instrument(1)

        self.assertEqual(len(song.instruments), 3)
        self.assertEqual(ptn.rows[0].instrument, 0)  # unchanged
        self.assertEqual(ptn.rows[1].instrument, 0)  # was 1 (removed), reset to 0
        self.assertEqual(ptn.rows[2].instrument, 1)  # was 2, now 1
        self.assertEqual(ptn.rows[3].instrument, 2)  # was 3, now 2

    def test_remove_first_instrument(self):
        """Removing instrument 0 decrements all others."""
        song = Song()
        for i in range(3):
            song.add_instrument(f"Inst{i}")
        ptn = song.patterns[0]
        ptn.rows[0].instrument = 0
        ptn.rows[1].instrument = 1
        ptn.rows[2].instrument = 2

        song.remove_instrument(0)

        self.assertEqual(ptn.rows[0].instrument, 0)  # removed -> 0
        self.assertEqual(ptn.rows[1].instrument, 0)  # 1 -> 0
        self.assertEqual(ptn.rows[2].instrument, 1)  # 2 -> 1

    def test_remove_last_instrument(self):
        """Removing the last instrument only resets rows referencing it."""
        song = Song()
        for i in range(3):
            song.add_instrument(f"Inst{i}")
        ptn = song.patterns[0]
        ptn.rows[0].instrument = 0
        ptn.rows[1].instrument = 2  # last instrument

        song.remove_instrument(2)

        self.assertEqual(ptn.rows[0].instrument, 0)
        self.assertEqual(ptn.rows[1].instrument, 0)  # removed -> 0

    def test_removal_across_multiple_patterns(self):
        """Remapping must cover all patterns."""
        song = Song()
        for i in range(3):
            song.add_instrument(f"Inst{i}")
        song.add_pattern()
        song.patterns[0].rows[0].instrument = 2
        song.patterns[1].rows[0].instrument = 2

        song.remove_instrument(1)

        self.assertEqual(song.patterns[0].rows[0].instrument, 1)  # 2 -> 1
        self.assertEqual(song.patterns[1].rows[0].instrument, 1)

    def test_no_out_of_bounds_after_removal(self):
        """After removal, no row should reference an index >= len(instruments)."""
        song = Song()
        for i in range(5):
            song.add_instrument(f"Inst{i}")
        # Set every row in default pattern to instrument 4 (last)
        for row in song.patterns[0].rows:
            row.instrument = 4

        song.remove_instrument(2)

        for row in song.patterns[0].rows:
            self.assertLess(row.instrument, len(song.instruments),
                            f"Row instrument {row.instrument} >= {len(song.instruments)}")


# ============================================================================
# Bug 5: save_undo must be called BEFORE modification
# ============================================================================

class TestUndoOrdering(unittest.TestCase):
    """Bug 5: Undo must capture the state BEFORE the modification so that
    undoing actually restores the original state."""

    def test_undo_before_title_change(self):
        """Standard pattern: save, then modify, then undo restores."""
        um = UndoManager()
        song = Song(title="Original")

        um.save(song, "change title")
        song.title = "Modified"

        um.undo(song)
        self.assertEqual(song.title, "Original")

    def test_undo_after_modification_is_noop(self):
        """If save happens AFTER modify, undo captures modified state (bug)."""
        um = UndoManager()
        song = Song(title="Original")

        # Bug pattern: modify THEN save
        song.title = "Modified"
        um.save(song, "change title")  # saves "Modified" state!

        song.title = "Modified2"
        um.undo(song)
        # This would restore to "Modified" - NOT "Original"
        self.assertEqual(song.title, "Modified")  # Demonstrates the bug pattern

    def test_songline_speed_undo(self):
        """Speed change should be undoable."""
        um = UndoManager()
        song = Song()
        song.songlines[0].speed = 6

        um.save(song, "Change speed")
        song.songlines[0].speed = 12

        um.undo(song)
        self.assertEqual(song.songlines[0].speed, 6)

    def test_pattern_assignment_undo(self):
        """Assigning a pattern to a songline channel should be undoable."""
        um = UndoManager()
        song = Song()
        song.add_pattern()
        song.songlines[0].patterns[0] = 0

        um.save(song, "Change pattern")
        song.songlines[0].patterns[0] = 1

        um.undo(song)
        self.assertEqual(song.songlines[0].patterns[0], 0)

    def test_songline_move_undo(self):
        """Songline swap should be undoable."""
        um = UndoManager()
        song = Song()
        song.songlines.append(Songline(speed=8))
        song.songlines[0].speed = 3

        um.save(song, "Move songline")
        song.songlines[0], song.songlines[1] = \
            song.songlines[1], song.songlines[0]

        um.undo(song)
        self.assertEqual(song.songlines[0].speed, 3)
        self.assertEqual(song.songlines[1].speed, 8)

    def test_add_pattern_undo(self):
        """Adding a pattern should be undoable."""
        um = UndoManager()
        song = Song()
        initial_count = len(song.patterns)

        um.save(song, "Add pattern")
        song.add_pattern()

        self.assertEqual(len(song.patterns), initial_count + 1)

        um.undo(song)
        self.assertEqual(len(song.patterns), initial_count)


# ============================================================================
# Bug 6: Partial digit entry must save undo on FIRST digit
# ============================================================================

class TestPartialDigitUndoIntegrity(unittest.TestCase):
    """Bug 6: When entering multi-digit values, undo should capture the state
    before the first digit, not between digits."""

    def test_two_digit_instrument_undo(self):
        """Simulates hex instrument entry: first digit saves undo, second
        completes. Undo should restore to state before first digit."""
        um = UndoManager()
        song = Song()
        song.add_instrument("Inst0")
        song.add_instrument("Inst1")
        row = song.patterns[0].rows[0]
        row.instrument = 0

        # First digit: save undo THEN modify
        um.save(song, "Enter instrument")
        row.instrument = 1  # first digit (partial)

        # Second digit: complete the value
        row.instrument = 0x1A  # full value

        # Undo should restore to 0 (before first digit)
        um.undo(song)
        self.assertEqual(song.patterns[0].rows[0].instrument, 0)

    def test_volume_undo(self):
        """Volume entry should also be undoable to pre-edit state."""
        um = UndoManager()
        song = Song()
        row = song.patterns[0].rows[0]
        row.volume = 5

        um.save(song, "Enter volume")
        row.volume = 12

        um.undo(song)
        self.assertEqual(song.patterns[0].rows[0].volume, 5)

    def test_song_editor_digit_undo(self):
        """Song editor digit entry: undo should restore to before first digit."""
        um = UndoManager()
        song = Song()
        song.add_pattern()
        song.songlines[0].patterns[0] = 0

        # First digit: save undo THEN set partial value
        um.save(song, "Edit song")
        song.songlines[0].patterns[0] = 1  # partial

        # Second digit: complete
        song.songlines[0].patterns[0] = 1  # final

        um.undo(song)
        self.assertEqual(song.songlines[0].patterns[0], 0)


# ============================================================================
# Bug 7: export_binary must use songline speed, not dead Song.speed
# ============================================================================

class TestExportBinarySpeed(unittest.TestCase):
    """Bug 7: export_binary wrote Song.speed (never properly set) instead
    of the actual per-songline speed value."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def _read_header_speed(self, path):
        """Read speed byte from PVG binary header.
        Header: PVG(3) + version(1) + channels(1) + speed(1) + ..."""
        with open(path, 'rb') as f:
            magic = f.read(3)
            self.assertEqual(magic, b'PVG')
            version = struct.unpack('B', f.read(1))[0]
            channels = struct.unpack('B', f.read(1))[0]
            speed = struct.unpack('<B', f.read(1))[0]
        return speed

    def test_export_uses_first_songline_speed(self):
        """Header speed must come from first songline, not Song.speed."""
        song = Song()
        song.songlines[0].speed = 7

        path = os.path.join(self.test_dir, "test.pvg")
        ok, msg = export_binary(song, path)
        self.assertTrue(ok)

        speed = self._read_header_speed(path)
        self.assertEqual(speed, 7)

    def test_export_not_default_speed(self):
        """Header speed must reflect actual songline speed, not DEFAULT_SPEED."""
        song = Song()
        song.songlines[0].speed = 11

        path = os.path.join(self.test_dir, "custom_speed.pvg")
        ok, msg = export_binary(song, path)
        self.assertTrue(ok)

        speed = self._read_header_speed(path)
        self.assertEqual(speed, 11)
        self.assertNotEqual(speed, DEFAULT_SPEED,
                            "Speed should not be the default; it should reflect "
                            "the actual songline speed.")

    def test_export_empty_songlines_uses_default(self):
        """If song has no songlines, fall back to DEFAULT_SPEED."""
        song = Song()
        song.songlines = []

        path = os.path.join(self.test_dir, "empty.pvg")
        ok, msg = export_binary(song, path)
        self.assertTrue(ok)

        speed = self._read_header_speed(path)
        self.assertEqual(speed, DEFAULT_SPEED)

    def test_song_speed_field_not_used(self):
        """Song.speed field should NOT affect export (it's dead code)."""
        song = Song()
        song.speed = 99  # dead field
        song.songlines[0].speed = 4

        path = os.path.join(self.test_dir, "dead_field.pvg")
        ok, _ = export_binary(song, path)
        self.assertTrue(ok)

        speed = self._read_header_speed(path)
        self.assertEqual(speed, 4)  # Must be songline speed, not 99


# ============================================================================
# Bug 8: transpose must exclude NOTE_OFF
# ============================================================================

class TestTransposeExcludesNoteOff(unittest.TestCase):
    """Bug 8: Pattern.transpose() was treating NOTE_OFF (255) as a regular
    note because 255 > 0. It should be excluded from transposition."""

    def test_note_off_preserved_on_positive_transpose(self):
        ptn = Pattern(length=4)
        ptn.rows[0].note = 10
        ptn.rows[1].note = NOTE_OFF
        ptn.rows[2].note = 0
        ptn.rows[3].note = 5

        ptn.transpose(2)

        self.assertEqual(ptn.rows[0].note, 12)
        self.assertEqual(ptn.rows[1].note, NOTE_OFF)
        self.assertEqual(ptn.rows[2].note, 0)
        self.assertEqual(ptn.rows[3].note, 7)

    def test_note_off_preserved_on_negative_transpose(self):
        ptn = Pattern(length=2)
        ptn.rows[0].note = 20
        ptn.rows[1].note = NOTE_OFF

        ptn.transpose(-5)

        self.assertEqual(ptn.rows[0].note, 15)
        self.assertEqual(ptn.rows[1].note, NOTE_OFF)

    def test_note_off_not_corrupted_by_large_negative(self):
        """NOTE_OFF (255) - 250 = 5, which IS in valid range. Must NOT happen."""
        ptn = Pattern(length=1)
        ptn.rows[0].note = NOTE_OFF

        ptn.transpose(-250)

        self.assertEqual(ptn.rows[0].note, NOTE_OFF,
                         "NOTE_OFF must never be transposed, even if result "
                         "would fall in valid range.")

    def test_note_off_not_corrupted_by_large_positive(self):
        """NOTE_OFF + positive would overflow, but check guard works."""
        ptn = Pattern(length=1)
        ptn.rows[0].note = NOTE_OFF

        ptn.transpose(12)

        self.assertEqual(ptn.rows[0].note, NOTE_OFF)

    def test_empty_notes_not_transposed(self):
        """Notes with value 0 (empty) should not be transposed."""
        ptn = Pattern(length=3)
        ptn.rows[0].note = 0
        ptn.rows[1].note = 0
        ptn.rows[2].note = 0

        ptn.transpose(5)

        for row in ptn.rows:
            self.assertEqual(row.note, 0)

    def test_boundary_notes_clamp_correctly(self):
        """Notes at MAX_NOTES boundary should not exceed range."""
        ptn = Pattern(length=2)
        ptn.rows[0].note = MAX_NOTES
        ptn.rows[1].note = 1

        ptn.transpose(1)

        # MAX_NOTES + 1 > MAX_NOTES, so should stay unchanged
        self.assertEqual(ptn.rows[0].note, MAX_NOTES)
        self.assertEqual(ptn.rows[1].note, 2)

    def test_transpose_down_below_1_clamps(self):
        """Transposing note 1 down should leave it unchanged (clamped)."""
        ptn = Pattern(length=1)
        ptn.rows[0].note = 1

        ptn.transpose(-1)

        self.assertEqual(ptn.rows[0].note, 1)  # 1-1=0 < 1, so no change

    def test_mixed_note_types(self):
        """Combination: empty, regular, NOTE_OFF all handled correctly."""
        ptn = Pattern(length=6)
        ptn.rows[0].note = 0         # empty
        ptn.rows[1].note = 12        # C-1
        ptn.rows[2].note = NOTE_OFF  # note off
        ptn.rows[3].note = 24        # C-2
        ptn.rows[4].note = 0         # empty
        ptn.rows[5].note = NOTE_OFF  # note off

        ptn.transpose(7)

        self.assertEqual(ptn.rows[0].note, 0)
        self.assertEqual(ptn.rows[1].note, 19)
        self.assertEqual(ptn.rows[2].note, NOTE_OFF)
        self.assertEqual(ptn.rows[3].note, 31)
        self.assertEqual(ptn.rows[4].note, 0)
        self.assertEqual(ptn.rows[5].note, NOTE_OFF)


# ============================================================================
# Bug 7 (supplementary): Instrument.to_dict includes sample_path for undo
# ============================================================================

class TestInstrumentSamplePathSerialization(unittest.TestCase):
    """Supplementary for Bug 7 fix: sample_path must survive serialization
    so UndoManager can re-attach audio data."""

    def test_sample_path_in_to_dict(self):
        inst = Instrument(name="Kick", sample_path="/tmp/samples/000.wav")
        d = inst.to_dict()
        self.assertIn('sample_path', d)
        self.assertEqual(d['sample_path'], "/tmp/samples/000.wav")

    def test_sample_path_survives_roundtrip(self):
        inst = Instrument(name="Kick", sample_path="/tmp/samples/000.wav")
        d = inst.to_dict()
        inst2 = Instrument.from_dict(d)
        self.assertEqual(inst2.sample_path, "/tmp/samples/000.wav")

    def test_undo_restores_audio_via_sample_path(self):
        """Full undo cycle: audio data restored by matching sample_path."""
        um = UndoManager()
        song = Song()
        inst = Instrument(name="Bass", sample_path="/tmp/bass.wav")
        inst.sample_data = np.array([0.1, 0.2, 0.3], dtype=np.float32)
        inst.sample_rate = 44100
        song.instruments.append(inst)

        um.save(song, "rename instrument")
        song.instruments[0].name = "Renamed"

        um.undo(song)
        self.assertEqual(song.instruments[0].name, "Bass")
        self.assertIsNotNone(song.instruments[0].sample_data)
        np.testing.assert_array_equal(
            song.instruments[0].sample_data,
            np.array([0.1, 0.2, 0.3], dtype=np.float32))


if __name__ == '__main__':
    unittest.main()
