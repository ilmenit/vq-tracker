"""Tests for 2D block selection, multi-channel clipboard, and text serialization."""
import sys, os, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from data_model import Row, Pattern, Song
from state import Selection, Clipboard
from constants import (MAX_CHANNELS, MAX_VOLUME, MAX_NOTES,
                       NOTE_OFF, VOL_CHANGE, note_to_str)
import clipboard_text


# =========================================================================
# Selection (2D block)
# =========================================================================

class TestSelection2D(unittest.TestCase):
    def setUp(self):
        self.sel = Selection()

    def test_initial_inactive(self):
        self.assertFalse(self.sel.active)
        self.assertIsNone(self.sel.get_block())
        self.assertIsNone(self.sel.get_range())
        self.assertFalse(self.sel.contains(0, 0))

    def test_begin(self):
        self.sel.begin(5, 2)
        self.assertTrue(self.sel.active)
        self.assertEqual(self.sel.get_block(), (5, 5, 2, 2))
        self.assertTrue(self.sel.contains(5, 2))
        self.assertFalse(self.sel.contains(5, 1))

    def test_extend_row_only(self):
        """extend(row) without channel → rows extend, channels stay."""
        self.sel.begin(2, 1)
        self.sel.extend(6)
        self.assertEqual(self.sel.get_block(), (2, 6, 1, 1))
        self.assertTrue(self.sel.contains(4, 1))
        self.assertFalse(self.sel.contains(4, 0))

    def test_extend_row_and_channel(self):
        """extend(row, channel) → full 2D rectangle."""
        self.sel.begin(2, 0)
        self.sel.extend(8, 3)
        self.assertEqual(self.sel.get_block(), (2, 8, 0, 3))
        self.assertTrue(self.sel.contains(5, 2))
        self.assertFalse(self.sel.contains(1, 2))
        self.assertFalse(self.sel.contains(9, 0))

    def test_extend_backwards(self):
        """Selection works when extending up-left (end < start)."""
        self.sel.begin(10, 3)
        self.sel.extend(2, 0)
        block = self.sel.get_block()
        self.assertEqual(block, (2, 10, 0, 3))
        self.assertTrue(self.sel.contains(5, 1))

    def test_clear(self):
        self.sel.begin(0, 0)
        self.sel.extend(10, 3)
        self.sel.clear()
        self.assertFalse(self.sel.active)
        self.assertIsNone(self.sel.get_block())

    def test_get_range_backward_compat(self):
        """get_range() returns row range only (backward-compatible)."""
        self.sel.begin(3, 1)
        self.sel.extend(7, 2)
        self.assertEqual(self.sel.get_range(), (3, 7))

    def test_num_rows_and_channels(self):
        self.sel.begin(2, 1)
        self.sel.extend(5, 3)
        self.assertEqual(self.sel.num_rows, 4)
        self.assertEqual(self.sel.num_channels, 3)

    def test_single_cell(self):
        self.sel.begin(0, 0)
        self.assertEqual(self.sel.num_rows, 1)
        self.assertEqual(self.sel.num_channels, 1)
        self.assertTrue(self.sel.contains(0, 0))
        self.assertFalse(self.sel.contains(0, 1))

    def test_channel_property_compat(self):
        """Legacy .channel property returns start_ch."""
        self.sel.begin(0, 2)
        self.assertEqual(self.sel.channel, 2)


# =========================================================================
# Clipboard (multi-channel)
# =========================================================================

class TestClipboardMultiChannel(unittest.TestCase):
    def test_copy_block(self):
        block = [
            [Row(1, 0, 15), Row(2, 1, 10)],
            [Row(3, 2, 8), Row(NOTE_OFF, 0, 15)],
        ]
        cb = Clipboard()
        cb.copy_block(block)
        self.assertTrue(cb.has_data())
        self.assertEqual(cb.num_channels, 2)
        self.assertEqual(cb.num_rows, 2)

    def test_paste_block_is_deep_copy(self):
        block = [[Row(5, 1, 10)]]
        cb = Clipboard()
        cb.copy_block(block)
        pasted = cb.paste_block()
        pasted[0][0].note = 99
        # Original should be unchanged
        self.assertEqual(cb.paste_block()[0][0].note, 5)

    def test_legacy_copy_paste(self):
        cb = Clipboard()
        cb.copy([Row(1, 0, 15), Row(2, 1, 10)])
        self.assertEqual(cb.num_channels, 1)
        self.assertEqual(cb.num_rows, 2)
        rows = cb.paste()
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0].note, 1)

    def test_clear(self):
        cb = Clipboard()
        cb.copy_block([[Row(1, 0, 15)]])
        cb.clear()
        self.assertFalse(cb.has_data())


# =========================================================================
# clipboard_text — serialization
# =========================================================================

class TestClipboardText(unittest.TestCase):
    def _make_block(self, note_grid):
        """Helper: note_grid[ch][row] → Block of Rows."""
        return [[Row(n, i, 15) for n in ch_notes]
                for i, ch_notes in enumerate(note_grid)]

    def test_roundtrip_basic(self):
        """Serialize → deserialize → identical."""
        block = [
            [Row(13, 0, 15), Row(NOTE_OFF, 0, 15), Row(0, 0, 15)],
            [Row(1, 1, 8), Row(VOL_CHANGE, 0, 10), Row(25, 2, 0)],
        ]
        text = clipboard_text.rows_to_text(block)
        result = clipboard_text.text_to_rows(text)
        self.assertIsNotNone(result)
        parsed, nch, nrows = result
        self.assertEqual(nch, 2)
        self.assertEqual(nrows, 3)
        # Check values
        self.assertEqual(parsed[0][0].note, 13)
        self.assertEqual(parsed[0][1].note, NOTE_OFF)
        self.assertEqual(parsed[0][2].note, 0)
        self.assertEqual(parsed[1][0].note, 1)
        self.assertEqual(parsed[1][0].volume, 8)
        self.assertEqual(parsed[1][1].note, VOL_CHANGE)
        self.assertEqual(parsed[1][2].note, 25)
        self.assertEqual(parsed[1][2].instrument, 2)
        self.assertEqual(parsed[1][2].volume, 0)

    def test_roundtrip_single_channel(self):
        block = [[Row(5, 0, 15)]]
        text = clipboard_text.rows_to_text(block)
        result = clipboard_text.text_to_rows(text)
        self.assertIsNotNone(result)
        parsed, nch, nrows = result
        self.assertEqual(nch, 1)
        self.assertEqual(nrows, 1)
        self.assertEqual(parsed[0][0].note, 5)

    def test_roundtrip_all_notes(self):
        """Round-trip every valid note (1-36) plus special values."""
        notes = list(range(0, MAX_NOTES + 1)) + [NOTE_OFF, VOL_CHANGE]
        block = [[Row(n, 0, MAX_VOLUME) for n in notes]]
        text = clipboard_text.rows_to_text(block)
        result = clipboard_text.text_to_rows(text)
        self.assertIsNotNone(result)
        parsed, _, _ = result
        for i, n in enumerate(notes):
            self.assertEqual(parsed[0][i].note, n,
                             f"Note {n} (row {i}): expected {n}, got {parsed[0][i].note}")

    def test_roundtrip_instruments(self):
        """Round-trip instrument values 0-127."""
        for inst in [0, 1, 10, 15, 16, 63, 127]:
            block = [[Row(1, inst, 15)]]
            text = clipboard_text.rows_to_text(block)
            result = clipboard_text.text_to_rows(text)
            self.assertIsNotNone(result)
            self.assertEqual(result[0][0][0].instrument, inst,
                             f"Instrument {inst} failed roundtrip")

    def test_roundtrip_volumes(self):
        """Round-trip volume values 0-15."""
        for vol in range(MAX_VOLUME + 1):
            block = [[Row(1, 0, vol)]]
            text = clipboard_text.rows_to_text(block)
            result = clipboard_text.text_to_rows(text)
            self.assertIsNotNone(result)
            self.assertEqual(result[0][0][0].volume, vol,
                             f"Volume {vol} failed roundtrip")

    def test_empty_block(self):
        text = clipboard_text.rows_to_text([])
        self.assertEqual(text, "")

    def test_invalid_text(self):
        self.assertIsNone(clipboard_text.text_to_rows(""))
        self.assertIsNone(clipboard_text.text_to_rows("random text"))
        self.assertIsNone(clipboard_text.text_to_rows("PVQT\t0\t0"))

    def test_header_magic(self):
        """Text must start with PVQT magic."""
        text = "WRONG\t2\t1\nC-1\t00\tF\tC-2\t00\tF"
        self.assertIsNone(clipboard_text.text_to_rows(text))

    def test_human_readable(self):
        """Text is human-readable and pasteable into Notepad."""
        block = [[Row(13, 5, 10), Row(NOTE_OFF, 0, 15)]]
        text = clipboard_text.rows_to_text(block)
        lines = text.split("\n")
        self.assertEqual(len(lines), 3)  # header + 2 rows
        self.assertTrue(lines[0].startswith("PVQT"))
        # Second line should contain note name
        self.assertIn("C-2", lines[1])  # note 13 = C-2
        self.assertIn("OFF", lines[2])

    def test_parse_note_variants(self):
        """Parser handles various note formats."""
        self.assertEqual(clipboard_text._parse_note("C-1"), 1)
        self.assertEqual(clipboard_text._parse_note("C#1"), 2)
        self.assertEqual(clipboard_text._parse_note("B-3"), 36)
        self.assertEqual(clipboard_text._parse_note("OFF"), NOTE_OFF)
        self.assertEqual(clipboard_text._parse_note("V--"), VOL_CHANGE)
        self.assertEqual(clipboard_text._parse_note("---"), 0)
        self.assertEqual(clipboard_text._parse_note("..."), 0)
        self.assertEqual(clipboard_text._parse_note(""), 0)

    def test_parse_tolerant_whitespace(self):
        """Parser is tolerant of whitespace around cells."""
        row = clipboard_text._cells_to_row("  C-2 ", " 05 ", " A ")
        self.assertEqual(row.note, 13)
        self.assertEqual(row.instrument, 5)
        self.assertEqual(row.volume, 10)

    def test_4ch_block(self):
        """4-channel block round-trips correctly."""
        block = [
            [Row(1, 0, 15), Row(0, 0, 15)],
            [Row(13, 1, 10), Row(NOTE_OFF, 0, 15)],
            [Row(0, 0, 15), Row(25, 2, 8)],
            [Row(VOL_CHANGE, 0, 5), Row(0, 0, 15)],
        ]
        text = clipboard_text.rows_to_text(block)
        result = clipboard_text.text_to_rows(text)
        self.assertIsNotNone(result)
        parsed, nch, nrows = result
        self.assertEqual(nch, 4)
        self.assertEqual(nrows, 2)
        self.assertEqual(parsed[0][0].note, 1)
        self.assertEqual(parsed[1][0].note, 13)
        self.assertEqual(parsed[2][1].note, 25)
        self.assertEqual(parsed[3][0].note, VOL_CHANGE)

    def test_text_editable_in_notepad(self):
        """Simulate user editing text in Notepad and pasting back."""
        # Original data
        block = [[Row(1, 0, 15), Row(13, 1, 10)]]
        text = clipboard_text.rows_to_text(block)

        # User changes note in Notepad: C-1 → D-1 (note 3)
        text = text.replace("C-1", "D-1")
        result = clipboard_text.text_to_rows(text)
        self.assertIsNotNone(result)
        parsed, _, _ = result
        self.assertEqual(parsed[0][0].note, 3)  # D-1
        self.assertEqual(parsed[0][1].note, 13)  # unchanged


class TestClipboardTextErrors(unittest.TestCase):
    """Robustness tests for corrupted/malformed clipboard text."""

    def test_bom_prefix(self):
        """UTF-8 BOM from Windows Notepad must be handled."""
        text = "\ufeffPVQT\t1\t1\nC-1\t00\tF"
        result = clipboard_text.text_to_rows(text)
        self.assertIsNotNone(result, "BOM should not prevent parsing")
        parsed, nch, nrows = result
        self.assertEqual(nch, 1)
        self.assertEqual(parsed[0][0].note, 1)

    def test_bom_raw_bytes(self):
        """Raw UTF-8 BOM bytes (\xef\xbb\xbf) also handled."""
        text = "\xef\xbb\xbfPVQT\t1\t1\nC-2\t00\tF"
        result = clipboard_text.text_to_rows(text)
        self.assertIsNotNone(result, "Raw BOM should not prevent parsing")
        parsed, _, _ = result
        self.assertEqual(parsed[0][0].note, 13)

    def test_crlf_line_endings(self):
        """Windows \\r\\n line endings must parse correctly."""
        text = "PVQT\t2\t2\r\nC-1\t00\tA\tD-1\t01\t8\r\nOFF\t--\tF\tC-2\t00\t5\r\n"
        result = clipboard_text.text_to_rows(text)
        self.assertIsNotNone(result)
        parsed, nch, nrows = result
        self.assertEqual(nch, 2)
        self.assertEqual(nrows, 2)
        self.assertEqual(parsed[0][0].note, 1)   # C-1
        self.assertEqual(parsed[0][0].volume, 10) # A
        self.assertEqual(parsed[1][0].note, 3)    # D-1
        self.assertEqual(parsed[1][0].volume, 8)  # 8 (not corrupted by \r)
        self.assertEqual(parsed[0][1].note, NOTE_OFF)
        self.assertEqual(parsed[1][1].note, 13)   # C-2
        self.assertEqual(parsed[1][1].volume, 5)   # 5

    def test_memory_bomb_capped(self):
        """Huge num_ch/num_rows capped to MAX_CHANNELS/MAX_ROWS."""
        text = "PVQT\t999999\t999999\nC-1\t00\tF"
        result = clipboard_text.text_to_rows(text)
        self.assertIsNotNone(result)
        parsed, nch, nrows = result
        self.assertEqual(nch, MAX_CHANNELS)  # capped to 4
        self.assertLessEqual(nrows, 254)     # capped to MAX_ROWS

    def test_num_ch_capped_to_4(self):
        """Channels beyond MAX_CHANNELS are silently dropped."""
        # Declare 8 channels but provide 8 columns of data
        cells = "\t".join(["C-1", "00", "F"] * 8)
        text = f"PVQT\t8\t1\n{cells}"
        result = clipboard_text.text_to_rows(text)
        self.assertIsNotNone(result)
        parsed, nch, _ = result
        self.assertEqual(nch, MAX_CHANNELS)  # only 4 parsed

    def test_blank_lines_produce_empty_rows(self):
        """Blank lines in data should produce empty rows, not crash."""
        text = "PVQT\t1\t3\nC-1\t00\tF\n\nC-2\t00\tF"
        result = clipboard_text.text_to_rows(text)
        self.assertIsNotNone(result)
        parsed, _, nrows = result
        self.assertEqual(nrows, 3)
        self.assertEqual(parsed[0][0].note, 1)   # C-1
        self.assertEqual(parsed[0][1].note, 0)   # blank line → empty row
        self.assertEqual(parsed[0][2].note, 13)  # C-2

    def test_short_data_lines_padded(self):
        """Lines with too few cells → missing channels get empty Row."""
        text = "PVQT\t2\t1\nC-1\t00\tF"  # only 1 channel of data
        result = clipboard_text.text_to_rows(text)
        self.assertIsNotNone(result)
        parsed, nch, _ = result
        self.assertEqual(nch, 2)
        self.assertEqual(parsed[0][0].note, 1)
        self.assertEqual(parsed[1][0].note, 0)  # no data → empty

    def test_fewer_data_lines_than_declared(self):
        """Header says 5 rows but only 2 data lines → rest padded."""
        text = "PVQT\t1\t5\nC-1\t00\tF\nC-2\t00\tF"
        result = clipboard_text.text_to_rows(text)
        self.assertIsNotNone(result)
        parsed, _, nrows = result
        self.assertEqual(nrows, 5)
        self.assertEqual(parsed[0][0].note, 1)
        self.assertEqual(parsed[0][1].note, 13)
        self.assertEqual(parsed[0][2].note, 0)  # padded
        self.assertEqual(parsed[0][4].note, 0)  # padded

    def test_garbage_note_values(self):
        """Unrecognized note strings default to 0 (empty)."""
        text = "PVQT\t1\t3\nHELLO\t00\tF\n123\t00\tF\n!@#\t00\tF"
        result = clipboard_text.text_to_rows(text)
        self.assertIsNotNone(result)
        parsed, _, _ = result
        self.assertEqual(parsed[0][0].note, 0)  # "HELLO" → 0
        self.assertEqual(parsed[0][1].note, 0)  # "123" out of range → 0
        self.assertEqual(parsed[0][2].note, 0)  # "!@#" → 0

    def test_garbage_inst_values(self):
        """Unrecognized instrument strings default to 0."""
        text = "PVQT\t1\t2\nC-1\tZZ\tF\nC-1\t\tF"
        result = clipboard_text.text_to_rows(text)
        self.assertIsNotNone(result)
        parsed, _, _ = result
        self.assertEqual(parsed[0][0].instrument, 0)  # "ZZ" → 0
        self.assertEqual(parsed[0][1].instrument, 0)  # "" → 0

    def test_garbage_vol_values(self):
        """Unrecognized volume strings default to MAX_VOLUME."""
        text = "PVQT\t1\t2\nC-1\t00\tXYZ\nC-1\t00\t"
        result = clipboard_text.text_to_rows(text)
        self.assertIsNotNone(result)
        parsed, _, _ = result
        self.assertEqual(parsed[0][0].volume, MAX_VOLUME)  # "XYZ" → MAX
        self.assertEqual(parsed[0][1].volume, MAX_VOLUME)  # "" → MAX

    def test_negative_header_values(self):
        """Negative channel/row count → returns None."""
        self.assertIsNone(clipboard_text.text_to_rows("PVQT\t-1\t5\nC-1\t00\tF"))
        self.assertIsNone(clipboard_text.text_to_rows("PVQT\t1\t-3\nC-1\t00\tF"))

    def test_float_header_values(self):
        """Float channel/row count → returns None."""
        self.assertIsNone(clipboard_text.text_to_rows("PVQT\t1.5\t3\nC-1\t00\tF"))

    def test_non_pvqt_text(self):
        """Random text that happens to start with P → rejected."""
        self.assertIsNone(clipboard_text.text_to_rows("PVQT is great\ndata"))
        self.assertIsNone(clipboard_text.text_to_rows("PVQTx\t1\t1\nC-1\t00\tF"))

    def test_only_header_no_data(self):
        """Header line but no data lines → returns None."""
        self.assertIsNone(clipboard_text.text_to_rows("PVQT\t1\t1"))

    def test_inst_out_of_range_clamped(self):
        """Instrument value > 127 is clamped."""
        text = "PVQT\t1\t1\nC-1\tFF\tF"
        result = clipboard_text.text_to_rows(text)
        self.assertIsNotNone(result)
        parsed, _, _ = result
        self.assertEqual(parsed[0][0].instrument, 127)  # FF=255 clamped to 127

    def test_vol_out_of_range_clamped(self):
        """Volume > F (15) in non-hex parse → clamped."""
        text = "PVQT\t1\t1\nC-1\t00\t99"
        result = clipboard_text.text_to_rows(text)
        self.assertIsNotNone(result)
        parsed, _, _ = result
        # "99" parsed as hex = 153, clamped to 15
        self.assertEqual(parsed[0][0].volume, MAX_VOLUME)

    def test_extra_tabs_in_line(self):
        """Extra tabs shift columns — last channel gets garbage → defaults."""
        # User accidentally added a tab before D-1
        text = "PVQT\t2\t1\nC-1\t00\tF\t\tD-1\t01\t8"
        result = clipboard_text.text_to_rows(text)
        self.assertIsNotNone(result)
        parsed, nch, _ = result
        self.assertEqual(nch, 2)
        self.assertEqual(parsed[0][0].note, 1)  # C-1 OK
        # Channel 2 is shifted: cells[3]="" cells[4]="D-1" cells[5]="01"
        # So ch1 gets note="" inst="D-1" vol="01"
        self.assertEqual(parsed[1][0].note, 0)  # "" → 0 (graceful degradation)


# =========================================================================
# Multi-channel copy/paste (integration)
# =========================================================================

class TestMultiChannelCopyPaste(unittest.TestCase):
    """Integration tests for multi-channel copy/paste using actual ops."""

    def setUp(self):
        from state import state
        self.state = state
        # Fresh song with 4 patterns
        self.state.song = Song()
        for _ in range(3):
            self.state.song.patterns.append(Pattern(length=16))
        self.state.song.songlines[0].patterns = [0, 1, 2, 3]
        self.state.songline = 0
        self.state.row = 0
        self.state.channel = 0
        self.state.column = 0
        self.state.selection.clear()
        self.state.clipboard.clear()
        self.state.audio = _DummyAudio()

        # Mock UI callbacks
        import ops.base
        ops.base.ui.refresh_editor = lambda: None
        ops.base.ui.refresh_all = lambda: None
        ops.base.ui.show_status = lambda msg: None
        ops.base.ui.refresh_song_editor = lambda: None
        ops.base.ui.refresh_instruments = lambda: None
        ops.base.ui.refresh_pattern_combo = lambda: None
        ops.base.ui.refresh_all_pattern_combos = lambda: None

        # Put some data in patterns
        p0 = self.state.song.get_pattern(0)
        p1 = self.state.song.get_pattern(1)
        for r in range(4):
            p0.rows[r] = Row(r + 1, 0, 15)
            p1.rows[r] = Row(r + 13, 1, 10)

    def test_copy_single_channel_no_selection(self):
        """Copy without selection → copies current row of current channel."""
        from ops.editing import copy_cells
        self.state.row = 2
        self.state.channel = 0
        copy_cells()
        self.assertTrue(self.state.clipboard.has_data())
        self.assertEqual(self.state.clipboard.num_channels, 1)
        self.assertEqual(self.state.clipboard.num_rows, 1)
        rows = self.state.clipboard.paste()
        self.assertEqual(rows[0].note, 3)  # row 2 of pattern 0

    def test_copy_block_2ch(self):
        """Copy 2-channel block selection."""
        from ops.editing import copy_cells
        self.state.selection.begin(0, 0)
        self.state.selection.extend(2, 1)
        copy_cells()
        self.assertEqual(self.state.clipboard.num_channels, 2)
        self.assertEqual(self.state.clipboard.num_rows, 3)
        block = self.state.clipboard.paste_block()
        self.assertEqual(block[0][0].note, 1)  # ch0 row0
        self.assertEqual(block[0][2].note, 3)  # ch0 row2
        self.assertEqual(block[1][0].note, 13)  # ch1 row0
        self.assertEqual(block[1][1].instrument, 1)

    def test_paste_block_2ch(self):
        """Paste 2-channel block at cursor position."""
        from ops.editing import paste_cells
        block = [
            [Row(20, 5, 8), Row(21, 5, 7)],
            [Row(22, 6, 6), Row(23, 6, 5)],
        ]
        self.state.clipboard.copy_block(block)
        self.state.row = 4
        self.state.channel = 1

        paste_cells()

        p1 = self.state.song.get_pattern(1)
        p2 = self.state.song.get_pattern(2)
        self.assertEqual(p1.rows[4].note, 20)
        self.assertEqual(p1.rows[5].note, 21)
        self.assertEqual(p2.rows[4].note, 22)
        self.assertEqual(p2.rows[5].note, 23)

    def test_paste_clips_to_channel_boundary(self):
        """Paste starting at channel 3 → only 1 channel of 2ch block fits."""
        from ops.editing import paste_cells
        block = [
            [Row(20, 0, 15)],
            [Row(21, 0, 15)],  # This would go to channel 4 (doesn't exist)
        ]
        self.state.clipboard.copy_block(block)
        self.state.row = 0
        self.state.channel = 3  # Last channel

        paste_cells()

        p3 = self.state.song.get_pattern(3)
        self.assertEqual(p3.rows[0].note, 20)
        # Channel 4 doesn't exist — no crash

    def test_paste_clips_to_row_boundary(self):
        """Paste past pattern length → rows beyond length are dropped."""
        from ops.editing import paste_cells
        block = [[Row(99, 0, 15)] * 20]  # 20 rows
        self.state.clipboard.copy_block(block)
        self.state.row = 14  # Pattern is 16 rows, only 2 fit

        paste_cells()

        p0 = self.state.song.get_pattern(0)
        self.assertEqual(p0.rows[14].note, 99)
        self.assertEqual(p0.rows[15].note, 99)

    def test_cut_block(self):
        """Cut 2-channel block → copies data and clears cells."""
        from ops.editing import cut_cells
        self.state.selection.begin(0, 0)
        self.state.selection.extend(1, 1)
        cut_cells()

        # Data should be in clipboard
        self.assertEqual(self.state.clipboard.num_channels, 2)
        self.assertEqual(self.state.clipboard.num_rows, 2)

        # Original cells should be cleared
        p0 = self.state.song.get_pattern(0)
        p1 = self.state.song.get_pattern(1)
        self.assertEqual(p0.rows[0].note, 0)
        self.assertEqual(p0.rows[1].note, 0)
        self.assertEqual(p1.rows[0].note, 0)
        self.assertEqual(p1.rows[1].note, 0)

    def test_clear_block(self):
        """Delete with block selection → clears rectangle."""
        from ops.editing import clear_cell
        self.state.selection.begin(0, 0)
        self.state.selection.extend(2, 1)
        clear_cell()

        p0 = self.state.song.get_pattern(0)
        p1 = self.state.song.get_pattern(1)
        for r in range(3):
            self.assertEqual(p0.rows[r].note, 0)
            self.assertEqual(p1.rows[r].note, 0)
        # Row 3 should be untouched
        self.assertEqual(p0.rows[3].note, 4)

    def test_copy_paste_roundtrip_via_text(self):
        """Copy → serialize → deserialize → paste → data matches."""
        from ops.editing import copy_cells
        self.state.selection.begin(0, 0)
        self.state.selection.extend(3, 1)
        copy_cells()

        block = self.state.clipboard.paste_block()
        text = clipboard_text.rows_to_text(block)
        result = clipboard_text.text_to_rows(text)
        self.assertIsNotNone(result)
        parsed, nch, nrows = result
        self.assertEqual(nch, 2)
        self.assertEqual(nrows, 4)
        self.assertEqual(parsed[0][0].note, 1)
        self.assertEqual(parsed[1][2].note, 15)

    def test_select_all(self):
        """select_all selects all rows × all channels."""
        from ops.navigation import select_all
        select_all()
        block = self.state.selection.get_block()
        self.assertIsNotNone(block)
        row_lo, row_hi, ch_lo, ch_hi = block
        self.assertEqual(row_lo, 0)
        self.assertEqual(ch_lo, 0)
        self.assertEqual(ch_hi, MAX_CHANNELS - 1)

    # -----------------------------------------------------------------
    # Channel mapping scenarios
    # -----------------------------------------------------------------

    def test_copy_1ch_paste_1ch(self):
        """Copy single channel, paste to a different channel."""
        from ops.editing import copy_cells, paste_cells
        # Select ch0 rows 0-3
        self.state.selection.begin(0, 0)
        self.state.selection.extend(3, 0)
        copy_cells()

        # Paste to ch2
        self.state.selection.clear()
        self.state.channel = 2
        self.state.row = 0
        paste_cells()

        p2 = self.state.song.get_pattern(2)
        self.assertEqual(p2.rows[0].note, 1)
        self.assertEqual(p2.rows[3].note, 4)

    def test_copy_2ch_paste_2ch(self):
        """Copy 2 channels, paste to 2 different channels."""
        from ops.editing import copy_cells, paste_cells
        # Select ch0-1 rows 0-2
        self.state.selection.begin(0, 0)
        self.state.selection.extend(2, 1)
        copy_cells()

        # Paste to ch2-3
        self.state.selection.clear()
        self.state.channel = 2
        self.state.row = 0
        paste_cells()

        p2 = self.state.song.get_pattern(2)
        p3 = self.state.song.get_pattern(3)
        self.assertEqual(p2.rows[0].note, 1)  # was ch0 data
        self.assertEqual(p2.rows[2].note, 3)
        self.assertEqual(p3.rows[0].note, 13) # was ch1 data
        self.assertEqual(p3.rows[0].instrument, 1)

    def test_copy_3ch_paste_3ch(self):
        """Copy 3 channels, paste starting at ch0."""
        from ops.editing import copy_cells, paste_cells
        # Put data in ch2
        p2 = self.state.song.get_pattern(2)
        p2.rows[0] = Row(25, 2, 5)

        self.state.selection.begin(0, 0)
        self.state.selection.extend(0, 2)
        copy_cells()

        self.assertEqual(self.state.clipboard.num_channels, 3)
        block = self.state.clipboard.paste_block()
        self.assertEqual(block[0][0].note, 1)   # ch0
        self.assertEqual(block[1][0].note, 13)  # ch1
        self.assertEqual(block[2][0].note, 25)  # ch2

    def test_copy_4ch_paste_4ch(self):
        """Copy all 4 channels, paste at ch0."""
        from ops.editing import copy_cells, paste_cells
        p2 = self.state.song.get_pattern(2)
        p3 = self.state.song.get_pattern(3)
        p2.rows[0] = Row(25, 2, 5)
        p3.rows[0] = Row(30, 3, 3)

        self.state.selection.begin(0, 0)
        self.state.selection.extend(0, 3)
        copy_cells()

        self.assertEqual(self.state.clipboard.num_channels, 4)

        # Clear all rows
        for pi in range(4):
            self.state.song.get_pattern(pi).rows[0].clear()

        self.state.channel = 0
        self.state.row = 0
        paste_cells()

        self.assertEqual(self.state.song.get_pattern(0).rows[0].note, 1)
        self.assertEqual(self.state.song.get_pattern(1).rows[0].note, 13)
        self.assertEqual(self.state.song.get_pattern(2).rows[0].note, 25)
        self.assertEqual(self.state.song.get_pattern(3).rows[0].note, 30)

    def test_copy_middle_2ch_paste_to_first_2ch(self):
        """Copy channels 1-2, paste to channels 0-1.

        This is the key scenario: channel offset is relative, not absolute.
        Data from ch1 goes to ch0, data from ch2 goes to ch1.
        """
        from ops.editing import copy_cells, paste_cells
        # Set up: ch1 has notes 13-16, ch2 has unique data
        p2 = self.state.song.get_pattern(2)
        for r in range(4):
            p2.rows[r] = Row(25 + r, 2, 5)

        # Select ch1-2 rows 0-3
        self.state.selection.begin(0, 1)
        self.state.selection.extend(3, 2)
        copy_cells()

        self.assertEqual(self.state.clipboard.num_channels, 2)
        block = self.state.clipboard.paste_block()
        # block[0] = ch1 data, block[1] = ch2 data (positional, not absolute)
        self.assertEqual(block[0][0].note, 13)  # from ch1
        self.assertEqual(block[1][0].note, 25)  # from ch2

        # Paste to ch0-1
        self.state.selection.clear()
        self.state.channel = 0
        self.state.row = 0
        paste_cells()

        p0 = self.state.song.get_pattern(0)
        p1 = self.state.song.get_pattern(1)
        # ch0 now has what was ch1's data
        self.assertEqual(p0.rows[0].note, 13)
        self.assertEqual(p0.rows[3].note, 16)
        self.assertEqual(p0.rows[0].instrument, 1)
        # ch1 now has what was ch2's data
        self.assertEqual(p1.rows[0].note, 25)
        self.assertEqual(p1.rows[3].note, 28)
        self.assertEqual(p1.rows[0].instrument, 2)

    def test_copy_middle_2ch_paste_to_last_2ch(self):
        """Copy ch1-2, paste to ch2-3 (partial overlap with source)."""
        from ops.editing import copy_cells, paste_cells
        p2 = self.state.song.get_pattern(2)
        p2.rows[0] = Row(25, 2, 5)

        self.state.selection.begin(0, 1)
        self.state.selection.extend(0, 2)
        copy_cells()

        self.state.selection.clear()
        self.state.channel = 2
        self.state.row = 0
        paste_cells()

        # ch2 gets ch1's data, ch3 gets ch2's data
        self.assertEqual(self.state.song.get_pattern(2).rows[0].note, 13)  # was ch1
        self.assertEqual(self.state.song.get_pattern(3).rows[0].note, 25)  # was ch2

    def test_copy_4ch_paste_at_ch2_clips(self):
        """Copy 4 channels, paste at ch2 → only 2 fit."""
        from ops.editing import copy_cells, paste_cells
        for pi in range(4):
            self.state.song.get_pattern(pi).rows[0] = Row(pi + 10, 0, 15)

        self.state.selection.begin(0, 0)
        self.state.selection.extend(0, 3)
        copy_cells()

        self.state.selection.clear()
        self.state.channel = 2
        self.state.row = 0
        paste_cells()

        # Only ch_offset 0 and 1 fit (→ target ch 2 and 3)
        self.assertEqual(self.state.song.get_pattern(2).rows[0].note, 10)  # was ch0
        self.assertEqual(self.state.song.get_pattern(3).rows[0].note, 11)  # was ch1

    def test_text_roundtrip_preserves_channel_count(self):
        """Copy 2ch → text → parse → paste → same data."""
        from ops.editing import copy_cells
        p2 = self.state.song.get_pattern(2)
        p2.rows[0] = Row(25, 2, 8)

        self.state.selection.begin(0, 1)
        self.state.selection.extend(0, 2)
        copy_cells()

        block = self.state.clipboard.paste_block()
        text = clipboard_text.rows_to_text(block)
        result = clipboard_text.text_to_rows(text)
        self.assertIsNotNone(result)
        parsed, nch, nrows = result
        self.assertEqual(nch, 2)
        self.assertEqual(nrows, 1)
        self.assertEqual(parsed[0][0].note, 13)
        self.assertEqual(parsed[0][0].instrument, 1)
        self.assertEqual(parsed[1][0].note, 25)
        self.assertEqual(parsed[1][0].instrument, 2)
        self.assertEqual(parsed[1][0].volume, 8)


class _DummyAudio:
    """Minimal audio engine mock for tests."""
    playing = False
    def is_playing(self): return self.playing
    def is_channel_enabled(self, ch): return True
    def set_song(self, song): pass
    def set_channel_enabled(self, ch, en): pass


class TestSharedPatternAutoClone(unittest.TestCase):
    """Tests that paste/cut/clear auto-clone shared patterns to prevent leaking."""

    def setUp(self):
        from state import state
        from data_model import Songline
        self.state = state
        self.state.audio = _DummyAudio()
        import ops.base
        ops.base.ui.refresh_editor = lambda: None
        ops.base.ui.refresh_all = lambda: None
        ops.base.ui.show_status = lambda msg: None
        ops.base.ui.refresh_song_editor = lambda: None
        ops.base.ui.refresh_instruments = lambda: None
        ops.base.ui.refresh_pattern_combo = lambda: None
        ops.base.ui.refresh_all_pattern_combos = lambda: None

        # Song with shared pattern: ch2 and ch3 share ptn2
        s = Song()
        s.patterns = [Pattern(length=16) for _ in range(4)]
        s.songlines = [Songline(patterns=[0, 1, 2, 2])]
        for r in range(4):
            s.get_pattern(0).rows[r] = Row(r + 1, 0, 15)
            s.get_pattern(1).rows[r] = Row(r + 13, 1, 10)
        self.state.song = s
        self.state.songline = 0
        self.state.row = 0
        self.state.channel = 0
        self.state.column = 0
        self.state.selection.clear()
        self.state.clipboard.clear()

    def test_paste_auto_clones_shared_pattern(self):
        """Pasting to ch2 (shared with ch3) clones ptn2 so ch3 is untouched."""
        from ops.editing import copy_cells, paste_cells

        self.state.selection.begin(0, 0)
        self.state.selection.extend(0, 1)
        copy_cells()

        self.state.selection.clear()
        self.state.channel = 1
        self.state.row = 0
        paste_cells()

        ptns = self.state.song.songlines[0].patterns
        # ch2 should have been cloned away from ch3
        self.assertNotEqual(ptns[2], ptns[3],
                            "ch2 and ch3 must no longer share a pattern")
        # ch3 keeps original ptn2 — must still be empty
        ch3_ptn = self.state.song.get_pattern(ptns[3])
        self.assertEqual(ch3_ptn.rows[0].note, 0, "ch3 must be untouched")
        # ch2 got pasted data (ch1's original = C-2)
        ch2_ptn = self.state.song.get_pattern(ptns[2])
        self.assertEqual(ch2_ptn.rows[0].note, 13)

    def test_paste_no_clone_when_not_shared(self):
        """Unique patterns are NOT cloned (no unnecessary pattern growth)."""
        from ops.editing import copy_cells, paste_cells
        from data_model import Songline

        self.state.song.songlines = [Songline(patterns=[0, 1, 2, 3])]
        num_before = len(self.state.song.patterns)

        self.state.selection.begin(0, 0)
        self.state.selection.extend(0, 0)
        copy_cells()

        self.state.selection.clear()
        self.state.channel = 1
        self.state.row = 0
        paste_cells()

        self.assertEqual(len(self.state.song.patterns), num_before,
                         "No patterns should be cloned when none are shared")

    def test_user_scenario_copy_ch01_paste_ch1(self):
        """User's exact scenario: copy ch0-1, paste at ch1.

        Songline: [0, 1, 2, 2] → ch2 and ch3 share ptn2.
        After paste: ch1 gets ch0 data, ch2 gets ch1 data (auto-cloned).
        ch3 must be untouched.
        """
        from ops.editing import copy_cells, paste_cells

        # Copy ch0 + ch1
        self.state.selection.begin(0, 0)
        self.state.selection.extend(3, 1)
        copy_cells()

        # Paste at ch1
        self.state.selection.clear()
        self.state.channel = 1
        self.state.row = 0
        paste_cells()

        ptns = self.state.song.songlines[0].patterns
        p_ch1 = self.state.song.get_pattern(ptns[1])
        p_ch2 = self.state.song.get_pattern(ptns[2])
        p_ch3 = self.state.song.get_pattern(ptns[3])

        # ch1 should now have ch0's original data (notes 1-4)
        self.assertEqual(p_ch1.rows[0].note, 1)
        self.assertEqual(p_ch1.rows[3].note, 4)
        # ch2 should have ch1's original data (notes 13-16)
        self.assertEqual(p_ch2.rows[0].note, 13)
        self.assertEqual(p_ch2.rows[3].note, 16)
        # ch3 must be completely untouched (empty)
        for r in range(4):
            self.assertEqual(p_ch3.rows[r].note, 0,
                             f"ch3 row {r} should be empty, got {p_ch3.rows[r].note}")

    def test_cut_auto_clones_shared_pattern(self):
        """Cut on shared pattern clones before clearing."""
        from ops.editing import cut_cells

        # Put data in the shared ptn2
        self.state.song.get_pattern(2).rows[0] = Row(25, 2, 8)

        # Select ch2 only and cut
        self.state.selection.begin(0, 2)
        self.state.selection.extend(0, 2)
        cut_cells()

        ptns = self.state.song.songlines[0].patterns
        # ch3 should still have the original data
        ch3_ptn = self.state.song.get_pattern(ptns[3])
        self.assertEqual(ch3_ptn.rows[0].note, 25,
                         "ch3 must retain original data after cut on ch2")

    def test_clear_block_auto_clones_shared_pattern(self):
        """Clear block on shared pattern clones before clearing."""
        from ops.editing import clear_cell

        self.state.song.get_pattern(2).rows[0] = Row(25, 2, 8)

        self.state.selection.begin(0, 2)
        self.state.selection.extend(0, 2)
        clear_cell()

        ptns = self.state.song.songlines[0].patterns
        ch3_ptn = self.state.song.get_pattern(ptns[3])
        self.assertEqual(ch3_ptn.rows[0].note, 25,
                         "ch3 must retain original data after clear on ch2")

    def test_both_targets_shared_with_same_pattern(self):
        """Two target channels sharing a pattern with each other — no clone needed."""
        from ops.editing import copy_cells, paste_cells
        from data_model import Songline

        # ch0-1 share ptn0, ch2-3 share ptn1 — paste to ch0-1
        self.state.song.songlines = [Songline(patterns=[0, 0, 1, 1])]
        self.state.song.get_pattern(0).rows[0] = Row(5, 0, 15)
        self.state.song.get_pattern(1).rows[0] = Row(10, 1, 10)
        num_before = len(self.state.song.patterns)

        # Copy from ch2-3
        self.state.selection.begin(0, 2)
        self.state.selection.extend(0, 3)
        copy_cells()

        # Paste to ch0-1 — both target the same ptn0, no non-target uses ptn0
        self.state.selection.clear()
        self.state.channel = 0
        self.state.row = 0
        paste_cells()

        # No clone needed since both ch0 and ch1 are targets
        self.assertEqual(len(self.state.song.patterns), num_before,
                         "No clone needed when all users of the pattern are targets")


if __name__ == "__main__":
    unittest.main()
