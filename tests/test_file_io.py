"""Tests for file_io.py - Project save/load, sample handling.

Covers:
- Project save/load round-trip with samples
- EditorState serialization
- Sample path remapping
- Safe filename generation
- Cross-user portability (different machines)
"""
import sys
import os
import tempfile
import shutil
import unittest
import zipfile
import json
import struct
import wave
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from constants import (MAX_VOLUME, DEFAULT_SPEED, FORMAT_VERSION, NOTE_OFF,
                       DEFAULT_OCTAVE, DEFAULT_STEP)
from data_model import Song, Instrument, Pattern, Row, Songline
from file_io import (
    save_project, load_project, EditorState, WorkingDirectory,
    load_sample,
)


class TestEditorState(unittest.TestCase):
    """Tests for EditorState serialization."""

    def test_defaults(self):
        es = EditorState()
        self.assertEqual(es.songline, 0)
        self.assertEqual(es.octave, DEFAULT_OCTAVE)
        self.assertTrue(es.hex_mode)

    def test_roundtrip(self):
        es = EditorState(
            songline=5, row=10, channel=2, column=1,
            octave=3, step=4, instrument=7, volume=12,
            hex_mode=False, follow=False,
            vq_rate=7917, vq_vector_size=4,
        )
        d = es.to_dict()
        es2 = EditorState.from_dict(d)
        self.assertEqual(es2.songline, 5)
        self.assertEqual(es2.row, 10)
        self.assertEqual(es2.channel, 2)
        self.assertEqual(es2.octave, 3)
        self.assertFalse(es2.hex_mode)
        self.assertEqual(es2.vq_rate, 7917)
        self.assertEqual(es2.vq_vector_size, 4)

    def test_from_dict_ignores_unknown_keys(self):
        """Unknown keys should be silently ignored (forward compatibility)."""
        d = {'songline': 3, 'future_key': True, 'another_new': 42}
        es = EditorState.from_dict(d)
        self.assertEqual(es.songline, 3)


class TestProjectSaveLoad(unittest.TestCase):
    """Integration tests for project save/load."""

    def setUp(self):
        """Create temporary directories for testing."""
        self.test_dir = tempfile.mkdtemp()
        self.work_dir = WorkingDirectory(self.test_dir)
        self.work_dir.init()

    def tearDown(self):
        """Clean up temporary directories."""
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def _create_test_wav(self, path: str, duration: float = 0.1,
                         rate: int = 44100) -> np.ndarray:
        """Create a minimal test WAV file."""
        samples = int(rate * duration)
        data = np.sin(np.linspace(0, 2 * np.pi * 440, samples)).astype(np.float32)
        data_int16 = (data * 32767).astype(np.int16)
        
        with wave.open(path, 'w') as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(rate)
            wf.writeframes(data_int16.tobytes())
        
        return data

    def test_save_load_empty_song(self):
        """Save and load an empty song."""
        song = Song(title="Empty Test", author="Tester")
        es = EditorState(octave=2, step=3)
        path = os.path.join(self.test_dir, "test.pvq")

        ok, msg = save_project(song, es, path, self.work_dir)
        self.assertTrue(ok, f"Save failed: {msg}")
        self.assertTrue(os.path.exists(path))

        song2, es2, msg2 = load_project(path, self.work_dir)
        self.assertIsNotNone(song2)
        self.assertEqual(song2.title, "Empty Test")
        self.assertEqual(song2.author, "Tester")
        self.assertEqual(es2.octave, 2)
        self.assertEqual(es2.step, 3)

    def test_save_load_with_patterns(self):
        """Song with pattern data round-trips correctly."""
        song = Song(title="Pattern Test")
        song.patterns[0].rows[0].note = 12
        song.patterns[0].rows[0].instrument = 3
        song.patterns[0].rows[0].volume = 10
        song.patterns[0].rows[5].note = NOTE_OFF

        es = EditorState()
        path = os.path.join(self.test_dir, "patterns.pvq")

        ok, msg = save_project(song, es, path, self.work_dir)
        self.assertTrue(ok)

        song2, _, _ = load_project(path, self.work_dir)
        self.assertEqual(song2.patterns[0].rows[0].note, 12)
        self.assertEqual(song2.patterns[0].rows[0].instrument, 3)
        self.assertEqual(song2.patterns[0].rows[0].volume, 10)
        self.assertEqual(song2.patterns[0].rows[5].note, NOTE_OFF)

    def test_save_load_with_samples(self):
        """Samples are embedded in ZIP and extracted on load."""
        song = Song(title="Sample Test")
        
        # Create a test WAV and add instrument
        wav_path = os.path.join(self.work_dir.samples, "00_kick.wav")
        audio_data = self._create_test_wav(wav_path)
        
        inst = Instrument(name="Kick", sample_path=wav_path)
        inst.sample_data = audio_data
        inst.sample_rate = 44100
        song.instruments.append(inst)

        es = EditorState()
        path = os.path.join(self.test_dir, "samples.pvq")

        ok, msg = save_project(song, es, path, self.work_dir)
        self.assertTrue(ok, f"Save failed: {msg}")
        self.assertIn("1 samples", msg)

        # Verify ZIP contents
        with zipfile.ZipFile(path, 'r') as zf:
            names = zf.namelist()
            self.assertIn("project.json", names)
            self.assertIn("metadata.json", names)
            sample_files = [n for n in names if n.startswith("samples/")]
            self.assertEqual(len(sample_files), 1)

        # Load on a fresh working directory (simulates another user)
        load_work_dir = WorkingDirectory(tempfile.mkdtemp())
        load_work_dir.init()
        try:
            song2, _, msg2 = load_project(path, load_work_dir)
            self.assertIsNotNone(song2)
            self.assertEqual(len(song2.instruments), 1)
            self.assertEqual(song2.instruments[0].name, "Kick")
            self.assertTrue(song2.instruments[0].is_loaded())
            self.assertIn("1 samples", msg2)
            # Sample path should point to extracted location
            self.assertTrue(os.path.exists(song2.instruments[0].sample_path))
        finally:
            shutil.rmtree(load_work_dir.root, ignore_errors=True)

    def test_vq_not_saved(self):
        """VQ conversion state should be reset on load."""
        song = Song()
        es = EditorState(vq_converted=True, vq_rate=7917)
        path = os.path.join(self.test_dir, "vq_test.pvq")

        save_project(song, es, path, self.work_dir)
        _, es2, _ = load_project(path, self.work_dir)

        # VQ should be marked as not converted (needs regeneration)
        self.assertFalse(es2.vq_converted)
        # But VQ settings should be preserved
        self.assertEqual(es2.vq_rate, 7917)

    def test_pvq_extension_auto_added(self):
        """Extension should be auto-added if missing."""
        song = Song()
        es = EditorState()
        path = os.path.join(self.test_dir, "noext")

        ok, _ = save_project(song, es, path, self.work_dir)
        self.assertTrue(ok)
        self.assertTrue(os.path.exists(path + ".pvq"))

    def test_invalid_file_load(self):
        """Loading non-existent file should fail gracefully."""
        song, es, msg = load_project("/nonexistent/path.pvq", self.work_dir)
        self.assertIsNone(song)
        self.assertIn("not found", msg)

    def test_corrupt_zip_load(self):
        """Loading corrupt ZIP should fail gracefully."""
        path = os.path.join(self.test_dir, "corrupt.pvq")
        with open(path, 'w') as f:
            f.write("not a zip file")

        song, es, msg = load_project(path, self.work_dir)
        self.assertIsNone(song)

    def test_missing_sample_warning(self):
        """Save should warn about missing sample files."""
        song = Song()
        inst = Instrument(name="Ghost", sample_path="/nonexistent/file.wav")
        song.instruments.append(inst)

        es = EditorState()
        path = os.path.join(self.test_dir, "missing.pvq")
        ok, msg = save_project(song, es, path, self.work_dir)
        self.assertTrue(ok)
        self.assertIn("WARNING", msg)

    def test_multiple_songlines(self):
        """Multiple songlines with different speeds round-trip."""
        song = Song(title="Multi")
        song.songlines[0].speed = 3
        song.songlines.append(Songline(patterns=[2, 1, 0, 3], speed=8))
        song.songlines.append(Songline(patterns=[0, 0, 0, 0], speed=12))

        es = EditorState(songline=2)
        path = os.path.join(self.test_dir, "multi.pvq")

        save_project(song, es, path, self.work_dir)
        song2, es2, _ = load_project(path, self.work_dir)

        self.assertEqual(len(song2.songlines), 3)
        self.assertEqual(song2.songlines[0].speed, 3)
        self.assertEqual(song2.songlines[1].patterns, [2, 1, 0, 3])
        self.assertEqual(song2.songlines[1].speed, 8)
        self.assertEqual(song2.songlines[2].speed, 12)
        self.assertEqual(es2.songline, 2)


class TestLoadSample(unittest.TestCase):
    """Tests for load_sample function."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def _create_wav(self, path: str, rate: int = 44100):
        samples = np.sin(np.linspace(0, 2 * np.pi * 440, rate // 10)).astype(np.float32)
        data_int16 = (samples * 32767).astype(np.int16)
        with wave.open(path, 'w') as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(rate)
            wf.writeframes(data_int16.tobytes())

    def test_load_valid_wav(self):
        path = os.path.join(self.test_dir, "test.wav")
        self._create_wav(path)
        inst = Instrument()
        ok, msg = load_sample(inst, path)
        self.assertTrue(ok)
        self.assertTrue(inst.is_loaded())
        self.assertEqual(inst.sample_rate, 44100)

    def test_load_nonexistent(self):
        inst = Instrument()
        ok, msg = load_sample(inst, "/nonexistent.wav")
        self.assertFalse(ok)

    def test_auto_name(self):
        path = os.path.join(self.test_dir, "kick_drum.wav")
        self._create_wav(path)
        inst = Instrument()
        ok, _ = load_sample(inst, path)
        self.assertTrue(ok)
        self.assertEqual(inst.name, "kick_drum")


if __name__ == '__main__':
    unittest.main()
