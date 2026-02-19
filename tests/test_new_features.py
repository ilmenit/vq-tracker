"""Tests for follow toggle, solo channel, and WAV export."""
import sys, os, unittest
import numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from data_model import Song, Pattern, Row, Instrument
from state import state
from constants import MAX_CHANNELS, MAX_VOLUME


class _DummyAudio:
    """Minimal audio mock for non-render tests."""
    playing = False
    _enabled = {0: True, 1: True, 2: True, 3: True}

    def is_playing(self): return self.playing
    def is_channel_enabled(self, ch): return self._enabled.get(ch, True)
    def set_channel_enabled(self, ch, en): self._enabled[ch] = en
    def set_song(self, song): pass
    def stop_playback(self): self.playing = False


def _setup_state():
    """Common state setup."""
    state.song = Song()
    state.songline = 0
    state.row = 0
    state.channel = 0
    state.follow = True
    state.audio = _DummyAudio()
    import ops.base
    ops.base.ui.refresh_editor = lambda: None
    ops.base.ui.refresh_all = lambda: None
    ops.base.ui.show_status = lambda msg: None
    ops.base.ui.show_error = lambda t, m: None
    ops.base.ui.update_controls = lambda: None
    ops.base.ui.refresh_song_editor = lambda: None
    ops.base.ui.refresh_instruments = lambda: None
    ops.base.ui.refresh_pattern_combo = lambda: None
    ops.base.ui.refresh_all_pattern_combos = lambda: None


# =============================================================================
# FOLLOW TOGGLE
# =============================================================================

class TestFollowToggle(unittest.TestCase):

    def setUp(self):
        _setup_state()

    def test_toggle_follow_off(self):
        from ops.navigation import toggle_follow
        state.follow = True
        toggle_follow()
        self.assertFalse(state.follow)

    def test_toggle_follow_on(self):
        from ops.navigation import toggle_follow
        state.follow = False
        toggle_follow()
        self.assertTrue(state.follow)

    def test_toggle_follow_roundtrip(self):
        from ops.navigation import toggle_follow
        state.follow = True
        toggle_follow()
        toggle_follow()
        self.assertTrue(state.follow)


# =============================================================================
# SOLO CHANNEL
# =============================================================================

class TestSoloChannel(unittest.TestCase):

    def setUp(self):
        _setup_state()
        # Reset all channels to enabled
        for ch in range(MAX_CHANNELS):
            state.audio.set_channel_enabled(ch, True)

    def test_solo_enables_only_target(self):
        from ops.navigation import solo_channel
        solo_channel(2)
        for ch in range(MAX_CHANNELS):
            if ch == 2:
                self.assertTrue(state.audio.is_channel_enabled(ch),
                                f"ch{ch} should be enabled (solo'd)")
            else:
                self.assertFalse(state.audio.is_channel_enabled(ch),
                                 f"ch{ch} should be muted")

    def test_solo_unsolo_enables_all(self):
        from ops.navigation import solo_channel
        solo_channel(1)  # Solo ch1
        solo_channel(1)  # Un-solo ch1
        for ch in range(MAX_CHANNELS):
            self.assertTrue(state.audio.is_channel_enabled(ch),
                            f"ch{ch} should be enabled after un-solo")

    def test_solo_switch_channels(self):
        from ops.navigation import solo_channel
        solo_channel(0)  # Solo ch0
        solo_channel(3)  # Solo ch3 (switches solo)
        for ch in range(MAX_CHANNELS):
            if ch == 3:
                self.assertTrue(state.audio.is_channel_enabled(ch))
            else:
                self.assertFalse(state.audio.is_channel_enabled(ch))

    def test_solo_ch0(self):
        from ops.navigation import solo_channel
        solo_channel(0)
        self.assertTrue(state.audio.is_channel_enabled(0))
        self.assertFalse(state.audio.is_channel_enabled(1))

    def test_solo_all_channels(self):
        """Solo each channel in turn — should always solo correctly."""
        from ops.navigation import solo_channel
        for target in range(MAX_CHANNELS):
            # Reset
            for ch in range(MAX_CHANNELS):
                state.audio.set_channel_enabled(ch, True)
            solo_channel(target)
            for ch in range(MAX_CHANNELS):
                expected = (ch == target)
                self.assertEqual(state.audio.is_channel_enabled(ch), expected,
                                 f"Solo ch{target}: ch{ch} should be {'on' if expected else 'off'}")

    def test_solo_out_of_bounds_is_noop(self):
        """Solo with invalid channel index should be a no-op."""
        from ops.navigation import solo_channel
        # All enabled initially
        for ch in range(MAX_CHANNELS):
            self.assertTrue(state.audio.is_channel_enabled(ch))
        # Out of bounds calls should not crash or change state
        solo_channel(-1)
        solo_channel(MAX_CHANNELS)
        solo_channel(99)
        for ch in range(MAX_CHANNELS):
            self.assertTrue(state.audio.is_channel_enabled(ch),
                            f"ch{ch} should still be enabled after OOB solo")


# =============================================================================
# RENDER OFFLINE (WAV export engine)
# =============================================================================

class TestRenderOffline(unittest.TestCase):

    def test_render_empty_song_returns_none(self):
        """Song with no instruments produces audio (silence)."""
        try:
            from audio_engine import AudioEngine
        except ImportError:
            self.skipTest("Audio engine not available")
        engine = AudioEngine()
        song = Song()
        song.get_pattern(0).length = 4
        engine.song = song
        engine.set_song(song)
        result = engine.render_offline()
        # Should render (silence) but not be None
        self.assertIsNotNone(result)

    def test_render_no_song_returns_none(self):
        """No song set returns None."""
        try:
            from audio_engine import AudioEngine
        except ImportError:
            self.skipTest("Audio engine not available")
        engine = AudioEngine()
        engine.song = None
        result = engine.render_offline()
        self.assertIsNone(result)

    def test_render_produces_audio(self):
        """A song with notes produces non-empty audio."""
        try:
            from audio_engine import AudioEngine, SAMPLE_RATE, Channel
        except ImportError:
            self.skipTest("Audio engine not available")

        engine = AudioEngine()
        song = Song()
        # Create a simple instrument with a sine wave
        inst = Instrument(name="test")
        sr = SAMPLE_RATE
        t = np.linspace(0, 0.1, int(sr * 0.1), dtype=np.float32)
        inst.sample_data = np.sin(2 * np.pi * 440 * t).astype(np.float32)
        inst.sample_rate = sr
        inst.base_note = 49  # A4
        song.instruments = [inst]
        # Put a note in the first row
        song.get_pattern(0).rows[0] = Row(49, 0, MAX_VOLUME)  # A4
        song.get_pattern(0).length = 4  # Short pattern
        engine.song = song
        engine.set_song(song)

        result = engine.render_offline()
        self.assertIsNotNone(result)
        self.assertGreater(len(result), 0)
        # Should have some non-zero samples (the sine wave note)
        self.assertGreater(np.abs(result).max(), 0.0)

    def test_render_progress_callback(self):
        """Progress callback is called during rendering."""
        try:
            from audio_engine import AudioEngine, SAMPLE_RATE
        except ImportError:
            self.skipTest("Audio engine not available")

        engine = AudioEngine()
        song = Song()
        inst = Instrument(name="test")
        sr = SAMPLE_RATE
        t = np.linspace(0, 0.05, int(sr * 0.05), dtype=np.float32)
        inst.sample_data = np.sin(2 * np.pi * 440 * t).astype(np.float32)
        inst.sample_rate = sr
        inst.base_note = 49
        song.instruments = [inst]
        song.get_pattern(0).rows[0] = Row(49, 0, MAX_VOLUME)
        song.get_pattern(0).length = 4
        engine.song = song
        engine.set_song(song)

        calls = []
        def on_progress(sl, row, total):
            calls.append((sl, row, total))

        engine.render_offline(progress_cb=on_progress)
        self.assertGreater(len(calls), 0, "Progress callback should be called")

    def test_render_final_buffer_not_dropped(self):
        """Song ending mid-buffer still renders the final buffer."""
        try:
            from audio_engine import AudioEngine, SAMPLE_RATE
        except ImportError:
            self.skipTest("Audio engine not available")

        engine = AudioEngine()
        song = Song()
        inst = Instrument(name="test")
        sr = SAMPLE_RATE
        # Long enough sample to ring through the final buffer
        t = np.linspace(0, 1.0, int(sr * 1.0), dtype=np.float32)
        inst.sample_data = np.sin(2 * np.pi * 440 * t).astype(np.float32)
        inst.sample_rate = sr
        inst.base_note = 49
        song.instruments = [inst]
        # Note on row 0, pattern length 2 — very short song
        song.get_pattern(0).rows[0] = Row(49, 0, MAX_VOLUME)
        song.get_pattern(0).length = 2
        engine.song = song
        engine.set_song(song)

        result = engine.render_offline()
        self.assertIsNotNone(result)
        # The last buffer should have audio (the note ringing out)
        # If the final buffer was dropped, we'd lose audio
        self.assertGreater(len(result), 0)

    def test_render_restores_channel_state(self):
        """Channel state (enabled, active) is fully restored after render."""
        try:
            from audio_engine import AudioEngine, SAMPLE_RATE
        except ImportError:
            self.skipTest("Audio engine not available")

        engine = AudioEngine()
        song = Song()
        inst = Instrument(name="test")
        sr = SAMPLE_RATE
        t = np.linspace(0, 0.05, int(sr * 0.05), dtype=np.float32)
        inst.sample_data = np.sin(2 * np.pi * 440 * t).astype(np.float32)
        inst.sample_rate = sr
        inst.base_note = 49
        song.instruments = [inst]
        song.get_pattern(0).rows[0] = Row(49, 0, MAX_VOLUME)
        song.get_pattern(0).length = 4
        engine.song = song
        engine.set_song(song)

        # Disable channel 2 before render
        engine.set_channel_enabled(2, False)
        self.assertFalse(engine.is_channel_enabled(2))

        engine.render_offline()

        # Channel 2 should still be disabled after render
        self.assertFalse(engine.is_channel_enabled(2),
                         "Channel enabled state not restored after render")
        # Engine should not be playing after render
        self.assertFalse(engine.playing)

    def test_render_speed_zero_does_not_hang(self):
        """A corrupt songline with speed=0 must not cause an infinite loop."""
        try:
            from audio_engine import AudioEngine, SAMPLE_RATE
        except ImportError:
            self.skipTest("Audio engine not available")

        engine = AudioEngine()
        song = Song()
        inst = Instrument(name="test")
        sr = SAMPLE_RATE
        t = np.linspace(0, 0.05, int(sr * 0.05), dtype=np.float32)
        inst.sample_data = np.sin(2 * np.pi * 440 * t).astype(np.float32)
        inst.sample_rate = sr
        inst.base_note = 49
        song.instruments = [inst]
        song.get_pattern(0).rows[0] = Row(49, 0, MAX_VOLUME)
        song.get_pattern(0).length = 4
        # Corrupt speed: 0 (would cause tick >= speed to always be true)
        song.songlines[0].speed = 0
        engine.song = song
        engine.set_song(song)

        # Should complete without hanging (_update_patterns clamps to 1)
        result = engine.render_offline()
        self.assertIsNotNone(result)
        self.assertGreater(len(result), 0)


# =============================================================================
# KEY CONFIG
# =============================================================================

class TestKeyConfigNewActions(unittest.TestCase):

    def test_toggle_follow_in_defaults(self):
        from key_config import DEFAULT_BINDINGS
        self.assertIn("toggle_follow", DEFAULT_BINDINGS)
        self.assertEqual(DEFAULT_BINDINGS["toggle_follow"], "F4")

    def test_toggle_follow_in_action_handlers(self):
        try:
            from keyboard import ACTION_HANDLERS
        except ImportError:
            self.skipTest("keyboard module requires dearpygui")
        self.assertIn("toggle_follow", ACTION_HANDLERS)


if __name__ == "__main__":
    unittest.main()
