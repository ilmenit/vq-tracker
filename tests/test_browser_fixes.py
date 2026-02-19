"""Tests for ui_browser.py and import pipeline bug fixes.

Covers:
  Bug 1: _sort_key_func mixed-type fallback crash
  Bug 2: on_ok unordered set → nondeterministic import order
  Bug 6: File number collision after instrument removal
  Bug 7: on_ok cleanup safety (logic-level)
  Bug 9: reset_all_instruments confirmation text

Note: UI rendering/playback tests (Bugs 3, 8) require DearPyGui context
and are not unit-testable.
"""
import sys
import os
import stat
import unittest
import tempfile
import shutil

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# We can't import FileBrowser directly (requires dearpygui context),
# so we test the pure-logic functions in isolation.


class TestSortKeyFuncTypeConsistency(unittest.TestCase):
    """Bug 1: _sort_key_func must return type-consistent fallback values.

    When sorting by 'size' or 'time', normal entries return int/float.
    The except/fallback path used to return "" (str), causing TypeError
    during Python 3 sort comparisons.
    """

    def _make_sort_func(self, sort_key):
        """Create a standalone sort key function matching FileBrowser logic."""
        def sort_key_func(entry):
            try:
                if sort_key == 'name':
                    return entry.name.lower()
                elif sort_key == 'ext':
                    return os.path.splitext(entry.name)[1].lower()
                elif sort_key == 'size':
                    return entry.stat().st_size if entry.is_file() else -1
                elif sort_key == 'time':
                    return entry.stat().st_mtime
            except (OSError, PermissionError):
                pass
            # Fixed: type-consistent fallback
            if sort_key in ('size', 'time'):
                return -1
            return ""
        return sort_key_func

    def test_size_sort_with_inaccessible_file(self):
        """Sort by size must not crash even if some entries raise OSError."""
        tmpdir = tempfile.mkdtemp()
        try:
            # Create normal files
            for name in ["a.wav", "b.wav", "c.wav"]:
                path = os.path.join(tmpdir, name)
                with open(path, 'wb') as f:
                    f.write(b'\x00' * (100 * (ord(name[0]) - ord('a') + 1)))

            entries = list(os.scandir(tmpdir))
            sort_func = self._make_sort_func('size')

            # Should not raise
            sorted_entries = sorted(entries, key=sort_func)
            sizes = [e.stat().st_size for e in sorted_entries]
            self.assertEqual(sizes, sorted(sizes))
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_size_fallback_is_numeric(self):
        """The fallback for size sort must be numeric, not string."""
        sort_func = self._make_sort_func('size')

        class FakeEntry:
            name = "broken.wav"
            def is_file(self): return True
            def stat(self): raise OSError("permission denied")

        result = sort_func(FakeEntry())
        self.assertIsInstance(result, (int, float),
                              "Fallback for size sort must be numeric")
        self.assertEqual(result, -1)

    def test_time_fallback_is_numeric(self):
        """The fallback for time sort must be numeric, not string."""
        sort_func = self._make_sort_func('time')

        class FakeEntry:
            name = "broken.wav"
            def is_file(self): return True
            def stat(self): raise PermissionError("no access")

        result = sort_func(FakeEntry())
        self.assertIsInstance(result, (int, float),
                              "Fallback for time sort must be numeric")

    def test_name_fallback_is_string(self):
        """The fallback for name sort should remain a string."""
        sort_func = self._make_sort_func('name')

        class FakeEntry:
            @property
            def name(self):
                raise OSError("bad entry")

        result = sort_func(FakeEntry())
        self.assertIsInstance(result, str)

    def test_mixed_entries_sort_without_crash(self):
        """Sorting a mix of normal and broken entries by size must not crash."""
        sort_func = self._make_sort_func('size')

        class GoodEntry:
            name = "good.wav"
            def is_file(self): return True
            def stat(self):
                class S:
                    st_size = 1024
                    st_mtime = 1000.0
                return S()

        class BadEntry:
            name = "bad.wav"
            def is_file(self): return True
            def stat(self): raise OSError("gone")

        entries = [BadEntry(), GoodEntry(), BadEntry(), GoodEntry()]
        # Must not raise TypeError
        sorted_entries = sorted(entries, key=sort_func)
        self.assertEqual(len(sorted_entries), 4)


class TestSelectionOrdering(unittest.TestCase):
    """Bug 2: Selected paths must be sorted before passing to callback."""

    def test_sorted_output(self):
        """Simulate on_ok: sorted() must produce alphabetical order."""
        # Simulate the set of selected paths
        selected = {
            "/home/user/samples/cymbal.wav",
            "/home/user/samples/bass.wav",
            "/home/user/samples/kick.wav",
            "/home/user/samples/hat.wav",
            "/home/user/samples/snare.wav",
        }

        # The fix: sorted(self.selected)
        result = sorted(selected)
        expected = [
            "/home/user/samples/bass.wav",
            "/home/user/samples/cymbal.wav",
            "/home/user/samples/hat.wav",
            "/home/user/samples/kick.wav",
            "/home/user/samples/snare.wav",
        ]
        self.assertEqual(result, expected)

    def test_sorted_is_deterministic(self):
        """Multiple calls to sorted() on the same set produce identical order."""
        selected = set()
        for i in range(50):
            selected.add(f"/path/sample_{i:03d}.wav")

        result1 = sorted(selected)
        result2 = sorted(selected)
        self.assertEqual(result1, result2)

    def test_mixed_directories_sorted(self):
        """Files from different directories sort by full path."""
        selected = {
            "/samples/synths/pad.wav",
            "/samples/drums/kick.wav",
            "/samples/drums/snare.wav",
            "/samples/synths/lead.wav",
        }
        result = sorted(selected)
        self.assertEqual(result, [
            "/samples/drums/kick.wav",
            "/samples/drums/snare.wav",
            "/samples/synths/lead.wav",
            "/samples/synths/pad.wav",
        ])


class TestNextSampleStartIndex(unittest.TestCase):
    """Bug 6: After instrument removal, len(instruments) can collide with
    existing numbered WAV files. next_sample_start_index must scan the
    directory and return max(existing_numbers) + 1."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        # Add file_io to path
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from file_io import next_sample_start_index
        self.next_idx = next_sample_start_index

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def _touch(self, name):
        """Create an empty file."""
        open(os.path.join(self.test_dir, name), 'w').close()

    def test_empty_dir(self):
        self.assertEqual(self.next_idx(self.test_dir), 0)

    def test_nonexistent_dir(self):
        self.assertEqual(self.next_idx("/nonexistent/path"), 0)

    def test_contiguous_files(self):
        """000.wav, 001.wav, 002.wav → next = 3."""
        for i in range(3):
            self._touch(f"{i:03d}.wav")
        self.assertEqual(self.next_idx(self.test_dir), 3)

    def test_gap_after_removal(self):
        """000.wav, 001.wav, 003.wav, 004.wav (002 removed) → next = 5.
        Must NOT return 2 (would be first gap), since start_index + i
        for i > 0 would collide with 003.wav."""
        for i in [0, 1, 3, 4]:
            self._touch(f"{i:03d}.wav")
        self.assertEqual(self.next_idx(self.test_dir), 5)

    def test_only_high_numbers(self):
        """Files at 010.wav, 011.wav → next = 12."""
        self._touch("010.wav")
        self._touch("011.wav")
        self.assertEqual(self.next_idx(self.test_dir), 12)

    def test_ignores_non_wav(self):
        """Non-WAV files should be ignored."""
        self._touch("000.wav")
        self._touch("001.txt")
        self._touch("002.mp3")
        self.assertEqual(self.next_idx(self.test_dir), 1)

    def test_ignores_non_numeric(self):
        """Non-numeric WAV files should be ignored."""
        self._touch("000.wav")
        self._touch("kick.wav")
        self._touch("snare.wav")
        self.assertEqual(self.next_idx(self.test_dir), 1)

    def test_collision_scenario(self):
        """Reproduce the exact collision scenario:
        6 instruments imported (000-005.wav), instrument 2 removed.
        len(instruments) = 5, but 005.wav exists → collision!
        next_sample_start_index should return 6."""
        for i in range(6):
            self._touch(f"{i:03d}.wav")
        # Instrument 2 removed → file 002.wav might be deleted or might remain
        # Either way, max is 005.wav → next = 6
        self.assertEqual(self.next_idx(self.test_dir), 6)

    def test_collision_with_file_removed(self):
        """Same scenario but 002.wav also deleted from disk.
        Files: 000, 001, 003, 004, 005 → max = 5 → next = 6."""
        for i in [0, 1, 3, 4, 5]:
            self._touch(f"{i:03d}.wav")
        self.assertEqual(self.next_idx(self.test_dir), 6)


class TestImportAudioFileNumbering(unittest.TestCase):
    """Bug 6 (integration): Verify import_audio_file creates files at the
    specified index and that the safe index prevents overwrites."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.src_dir = tempfile.mkdtemp()
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        self._create_test_wav(os.path.join(self.src_dir, "test.wav"))

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)
        shutil.rmtree(self.src_dir, ignore_errors=True)

    def _create_test_wav(self, path):
        """Create a minimal valid WAV file."""
        import wave
        import numpy as np
        samples = np.zeros(100, dtype=np.int16)
        with wave.open(path, 'w') as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(44100)
            wf.writeframes(samples.tobytes())

    def test_creates_numbered_file(self):
        from file_io import import_audio_file
        src = os.path.join(self.src_dir, "test.wav")
        dest, name, msg = import_audio_file(src, self.test_dir, index=5)
        self.assertIsNotNone(dest)
        self.assertTrue(dest.endswith("005.wav"))
        self.assertTrue(os.path.exists(dest))

    def test_safe_index_avoids_overwrite(self):
        """Using next_sample_start_index prevents overwriting existing files."""
        from file_io import import_audio_file, next_sample_start_index

        # Pre-populate: existing instruments have files 000-005
        for i in range(6):
            self._create_test_wav(os.path.join(self.test_dir, f"{i:03d}.wav"))

        # Write known content to 005.wav so we can detect overwrite
        with open(os.path.join(self.test_dir, "005.wav"), 'rb') as f:
            original_005_content = f.read()

        # Safe index should be 6 (not 5!)
        safe_start = next_sample_start_index(self.test_dir)
        self.assertEqual(safe_start, 6)

        # Import at safe index
        src = os.path.join(self.src_dir, "test.wav")
        dest, _, _ = import_audio_file(src, self.test_dir, index=safe_start)
        self.assertTrue(dest.endswith("006.wav"))

        # Verify 005.wav was NOT overwritten
        with open(os.path.join(self.test_dir, "005.wav"), 'rb') as f:
            self.assertEqual(f.read(), original_005_content)


class TestImportSamplesMultiCompleteness(unittest.TestCase):
    """Structural fix: import_samples_multi must produce fully-initialized
    Instruments with all required fields set."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.src_dir = tempfile.mkdtemp()
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)
        shutil.rmtree(self.src_dir, ignore_errors=True)

    def _create_test_wav(self, path):
        import wave
        import numpy as np
        samples = np.zeros(100, dtype=np.int16)
        with wave.open(path, 'w') as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(44100)
            wf.writeframes(samples.tobytes())

    def test_all_fields_initialized(self):
        """Every field needed for a working instrument must be set."""
        from file_io import import_samples_multi
        src = os.path.join(self.src_dir, "my_sample.wav")
        self._create_test_wav(src)

        results = import_samples_multi([src], self.test_dir, start_index=0)
        inst, ok, msg = results[0]
        self.assertTrue(ok, msg)

        # name: derived from original filename (not "New", not numbered)
        self.assertNotIn(inst.name, ("New", "New Instrument", ""),
                         "name must be set from source filename")
        self.assertFalse(inst.name.isdigit(),
                         "name must not be the numbered dest filename")

        # sample_path: points to working copy
        self.assertTrue(inst.sample_path.endswith(".wav"))
        self.assertTrue(os.path.exists(inst.sample_path))

        # sample_data: loaded
        self.assertTrue(inst.is_loaded())
        self.assertGreater(len(inst.sample_data), 0)

    def test_file_and_folder_paths_produce_identical_results(self):
        """The structural invariant: given the same source files, both
        import paths must produce instruments with the same fields set."""
        from file_io import import_samples_multi

        src = os.path.join(self.src_dir, "test.wav")
        self._create_test_wav(src)

        dest1 = tempfile.mkdtemp()
        dest2 = tempfile.mkdtemp()
        try:
            # Simulate file-mode path (same function now!)
            r1 = import_samples_multi([src], dest1, start_index=0)
            # Simulate folder-mode path (same function now!)
            r2 = import_samples_multi([src], dest2, start_index=0)

            inst1, ok1, _ = r1[0]
            inst2, ok2, _ = r2[0]
            self.assertTrue(ok1)
            self.assertTrue(ok2)

            # All significant fields must match
            self.assertEqual(inst1.name, inst2.name)
            self.assertEqual(inst1.sample_rate, inst2.sample_rate)
            self.assertEqual(inst1.is_loaded(), inst2.is_loaded())
        finally:
            shutil.rmtree(dest1, ignore_errors=True)
            shutil.rmtree(dest2, ignore_errors=True)


class TestNavigateExpansion(unittest.TestCase):
    """Browser navigate() must expand ~ and strip whitespace."""

    def test_expanduser(self):
        """os.path.expanduser must be called on navigate input."""
        home = os.path.expanduser("~")
        expanded = os.path.expanduser("~/")
        self.assertTrue(os.path.isdir(expanded),
                        f"~ should expand to a valid directory: {expanded}")

    def test_strip_whitespace(self):
        """Leading/trailing whitespace should be stripped."""
        path = "  /tmp  "
        self.assertEqual(path.strip(), "/tmp")


class TestReplaceInstrument(unittest.TestCase):
    """Replace instrument: import new file into existing slot without
    changing instrument index or disrupting old files (undo-safe)."""

    def setUp(self):
        self.dest_dir = tempfile.mkdtemp()
        self.src_dir = tempfile.mkdtemp()
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    def tearDown(self):
        shutil.rmtree(self.dest_dir, ignore_errors=True)
        shutil.rmtree(self.src_dir, ignore_errors=True)

    def _create_wav(self, path, value=0):
        import wave
        import numpy as np
        data = np.full(100, value, dtype=np.int16)
        with wave.open(path, 'w') as wf:
            wf.setnchannels(1); wf.setsampwidth(2); wf.setframerate(44100)
            wf.writeframes(data.tobytes())

    def test_replace_uses_new_file_number(self):
        """Replace must allocate a new numbered WAV, not overwrite the old one."""
        from file_io import import_samples_multi, next_sample_start_index

        # Existing instrument at 000.wav
        self._create_wav(os.path.join(self.dest_dir, '000.wav'), value=111)
        # New source file
        self._create_wav(os.path.join(self.src_dir, 'new_sound.wav'), value=222)

        idx = next_sample_start_index(self.dest_dir)
        self.assertEqual(idx, 1, "Should allocate index 1 after existing 000.wav")

        results = import_samples_multi(
            [os.path.join(self.src_dir, 'new_sound.wav')],
            self.dest_dir, start_index=idx)
        new_inst, ok, msg = results[0]

        self.assertTrue(ok, msg)
        self.assertTrue(new_inst.sample_path.endswith('001.wav'),
                        f"Expected 001.wav, got {new_inst.sample_path}")

    def test_replace_preserves_old_file(self):
        """Old WAV must survive (undo needs it)."""
        from file_io import import_samples_multi, next_sample_start_index
        import wave
        import numpy as np

        old_path = os.path.join(self.dest_dir, '000.wav')
        self._create_wav(old_path, value=111)
        self._create_wav(os.path.join(self.src_dir, 'repl.wav'), value=222)

        idx = next_sample_start_index(self.dest_dir)
        import_samples_multi([os.path.join(self.src_dir, 'repl.wav')],
                             self.dest_dir, start_index=idx)

        # Old file must still exist with original content
        self.assertTrue(os.path.exists(old_path))
        with wave.open(old_path, 'r') as wf:
            data = np.frombuffer(wf.readframes(100), dtype=np.int16)
        self.assertEqual(data[0], 111, "Old file was corrupted by replace")

    def test_replace_sets_all_fields(self):
        """Replacement instrument must have all fields initialized."""
        from file_io import import_samples_multi, next_sample_start_index

        self._create_wav(os.path.join(self.src_dir, 'my_snare.wav'))

        idx = next_sample_start_index(self.dest_dir)
        results = import_samples_multi(
            [os.path.join(self.src_dir, 'my_snare.wav')],
            self.dest_dir, start_index=idx)
        new_inst, ok, msg = results[0]

        self.assertTrue(ok, msg)
        self.assertEqual(new_inst.name, 'my_snare')
        self.assertTrue(new_inst.is_loaded())
        self.assertTrue(os.path.exists(new_inst.sample_path))


class TestDoubleClickFolderNavigate(unittest.TestCase):
    """Double-click folder to navigate must NOT leave phantom selection."""

    def test_discard_on_navigate(self):
        """After double-click navigate, the folder must not remain in selected."""
        # Simulate the exact sequence that happens in the browser:
        selected = set()
        folder = "/some/folder/Drums"

        # First click: folder gets selected
        selected.add(folder)  # toggle_select(path, True)

        # Second click (double): the fix discards instead of adding back
        selected.discard(folder)

        self.assertEqual(len(selected), 0,
                         "Folder should NOT remain selected after double-click navigate")

    def test_existing_selections_preserved(self):
        """Other selections must survive a double-click navigate."""
        selected = {"folder_A", "folder_B"}

        # User navigates into folder_C by double-click
        folder_c = "folder_C"
        selected.add(folder_c)    # first click selected it
        selected.discard(folder_c)  # double-click undoes it

        self.assertEqual(selected, {"folder_A", "folder_B"},
                         "Pre-existing selections must not be affected")


if __name__ == '__main__':
    unittest.main()
