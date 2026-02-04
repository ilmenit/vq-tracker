"""Tests for state.py - UndoManager, Selection, Clipboard.

Covers:
- Undo/redo stack behavior
- Audio reference preservation across undo
- Selection range calculations
- Clipboard copy/paste
"""
import sys
import os
import unittest
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Mock sounddevice if not available (it's not needed for state tests)
try:
    import sounddevice
except (ImportError, OSError):
    import types
    sd_mock = types.ModuleType('sounddevice')
    sd_mock.__version__ = '0.0.0'
    sys.modules['sounddevice'] = sd_mock

from constants import MAX_VOLUME, NOTE_OFF
from data_model import Row, Pattern, Song, Instrument
from state import UndoManager, Selection, Clipboard


class TestUndoManager(unittest.TestCase):
    """Tests for UndoManager."""

    def test_initial_state(self):
        um = UndoManager()
        self.assertFalse(um.can_undo())
        self.assertFalse(um.can_redo())

    def test_save_and_undo(self):
        um = UndoManager()
        song = Song()
        song.title = "Before"
        um.save(song, "change title")
        song.title = "After"
        
        desc = um.undo(song)
        self.assertEqual(desc, "change title")
        self.assertEqual(song.title, "Before")

    def test_redo(self):
        um = UndoManager()
        song = Song()
        song.title = "Before"
        um.save(song, "change")
        song.title = "After"
        
        um.undo(song)
        self.assertEqual(song.title, "Before")
        
        um.redo(song)
        self.assertEqual(song.title, "After")

    def test_undo_empty(self):
        um = UndoManager()
        song = Song()
        result = um.undo(song)
        self.assertIsNone(result)

    def test_redo_empty(self):
        um = UndoManager()
        song = Song()
        result = um.redo(song)
        self.assertIsNone(result)

    def test_save_clears_redo(self):
        um = UndoManager()
        song = Song()
        um.save(song, "1")
        song.title = "v1"
        um.save(song, "2")
        song.title = "v2"
        
        um.undo(song)  # Back to v1
        self.assertTrue(um.can_redo())
        
        um.save(song, "3")  # New action clears redo
        self.assertFalse(um.can_redo())

    def test_max_size(self):
        um = UndoManager(max_size=3)
        song = Song()
        for i in range(5):
            um.save(song, f"action {i}")
            song.title = f"v{i}"
        
        self.assertEqual(len(um.undo_stack), 3)

    def test_audio_reference_preservation(self):
        """Audio data should survive undo/redo via reference tracking."""
        um = UndoManager()
        song = Song()
        
        # Add instrument with audio data
        inst = Instrument(name="Bass", sample_path="/tmp/bass.wav")
        inst.sample_data = np.array([0.1, 0.2, 0.3], dtype=np.float32)
        inst.sample_rate = 44100
        song.instruments.append(inst)
        
        um.save(song, "before rename")
        song.instruments[0].name = "Renamed Bass"
        
        um.undo(song)
        self.assertEqual(song.instruments[0].name, "Bass")
        # Audio data should be restored via reference
        self.assertIsNotNone(song.instruments[0].sample_data)
        np.testing.assert_array_equal(
            song.instruments[0].sample_data,
            np.array([0.1, 0.2, 0.3], dtype=np.float32)
        )

    def test_clear(self):
        um = UndoManager()
        song = Song()
        um.save(song, "1")
        um.save(song, "2")
        um.clear()
        self.assertFalse(um.can_undo())
        self.assertFalse(um.can_redo())

    def test_pattern_data_undo(self):
        """Pattern edits should undo correctly."""
        um = UndoManager()
        song = Song()
        
        um.save(song, "edit note")
        song.patterns[0].rows[0].note = 12
        song.patterns[0].rows[0].instrument = 3
        
        um.undo(song)
        self.assertEqual(song.patterns[0].rows[0].note, 0)
        self.assertEqual(song.patterns[0].rows[0].instrument, 0)


class TestSelection(unittest.TestCase):
    """Tests for Selection."""

    def test_initial_state(self):
        sel = Selection()
        self.assertFalse(sel.active)
        self.assertIsNone(sel.get_range())

    def test_begin_and_extend(self):
        sel = Selection()
        sel.begin(5, 0)
        self.assertTrue(sel.active)
        sel.extend(10)
        start, end = sel.get_range()
        self.assertEqual(start, 5)
        self.assertEqual(end, 10)

    def test_reverse_selection(self):
        sel = Selection()
        sel.begin(10, 0)
        sel.extend(5)
        start, end = sel.get_range()
        self.assertEqual(start, 5)
        self.assertEqual(end, 10)

    def test_contains(self):
        sel = Selection()
        sel.begin(3, 1)
        sel.extend(7)
        self.assertTrue(sel.contains(5, 1))
        self.assertFalse(sel.contains(5, 0))  # Wrong channel
        self.assertFalse(sel.contains(10, 1))  # Out of range

    def test_clear(self):
        sel = Selection()
        sel.begin(3, 0)
        sel.extend(7)
        sel.clear()
        self.assertFalse(sel.active)
        self.assertIsNone(sel.get_range())


class TestClipboard(unittest.TestCase):
    """Tests for Clipboard."""

    def test_initial_state(self):
        cb = Clipboard()
        self.assertFalse(cb.has_data())
        self.assertEqual(cb.paste(), [])

    def test_copy_paste(self):
        cb = Clipboard()
        rows = [Row(note=12), Row(note=24)]
        cb.copy(rows, channel=1)
        self.assertTrue(cb.has_data())
        
        pasted = cb.paste()
        self.assertEqual(len(pasted), 2)
        self.assertEqual(pasted[0].note, 12)
        self.assertEqual(pasted[1].note, 24)

    def test_paste_returns_copies(self):
        cb = Clipboard()
        rows = [Row(note=12)]
        cb.copy(rows)
        
        p1 = cb.paste()
        p2 = cb.paste()
        p1[0].note = 99
        self.assertEqual(p2[0].note, 12)  # Should be independent

    def test_clear(self):
        cb = Clipboard()
        cb.copy([Row(note=12)])
        cb.clear()
        self.assertFalse(cb.has_data())


if __name__ == '__main__':
    unittest.main()
