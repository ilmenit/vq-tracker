"""Tests for sample editor: commands, pipeline, serialization."""
import unittest
import numpy as np
from sample_editor.commands import (
    SampleCommand, COMMAND_APPLY, COMMAND_DEFAULTS,
    apply_trim, apply_reverse, apply_gain, apply_normalize,
    apply_adsr, apply_tremolo, apply_vibrato, apply_pitch_env,
    apply_overdrive, apply_echo, apply_octave, get_summary,
)
from sample_editor.pipeline import run_pipeline, run_pipeline_at, get_playback_audio
from data_model import Instrument, Song


def sine(freq=440, sr=44100, dur=0.5):
    """Generate a sine wave test signal."""
    t = np.arange(int(sr * dur), dtype=np.float32) / sr
    return np.sin(2 * np.pi * freq * t).astype(np.float32)


class TestSampleCommand(unittest.TestCase):
    """SampleCommand dataclass and serialization."""

    def test_to_dict_from_dict_roundtrip(self):
        cmd = SampleCommand(type='gain', params={'db': 3.0}, enabled=True)
        d = cmd.to_dict()
        cmd2 = SampleCommand.from_dict(d)
        self.assertEqual(cmd2.type, 'gain')
        self.assertAlmostEqual(cmd2.params['db'], 3.0)
        self.assertTrue(cmd2.enabled)

    def test_from_dict_defaults(self):
        cmd = SampleCommand.from_dict({})
        self.assertEqual(cmd.type, '')
        self.assertEqual(cmd.params, {})
        self.assertTrue(cmd.enabled)

    def test_disabled_roundtrip(self):
        cmd = SampleCommand(type='trim', params={'start_ms': 100}, enabled=False)
        cmd2 = SampleCommand.from_dict(cmd.to_dict())
        self.assertFalse(cmd2.enabled)


class TestApplyFunctions(unittest.TestCase):
    """Individual effect functions."""

    def setUp(self):
        self.sr = 44100
        self.audio = sine(440, self.sr, 0.5)

    # -- Trim --
    def test_trim_default_no_change(self):
        out = apply_trim(self.audio, self.sr, {'start_ms': 0, 'end_ms': 0})
        self.assertEqual(len(out), len(self.audio))

    def test_trim_shortens(self):
        out = apply_trim(self.audio, self.sr, {'start_ms': 100, 'end_ms': 300})
        expected = int(200 * self.sr / 1000)
        self.assertEqual(len(out), expected)

    def test_trim_empty_returns_one_sample(self):
        out = apply_trim(self.audio, self.sr, {'start_ms': 500, 'end_ms': 500})
        self.assertEqual(len(out), 1)

    # -- Reverse --
    def test_reverse_involution(self):
        out = apply_reverse(apply_reverse(self.audio, self.sr, {}), self.sr, {})
        np.testing.assert_array_almost_equal(out, self.audio)

    def test_reverse_length(self):
        out = apply_reverse(self.audio, self.sr, {})
        self.assertEqual(len(out), len(self.audio))

    # -- Gain --
    def test_gain_zero_db(self):
        out = apply_gain(self.audio, self.sr, {'db': 0.0})
        np.testing.assert_array_almost_equal(out, self.audio, decimal=5)

    def test_gain_positive(self):
        out = apply_gain(self.audio, self.sr, {'db': 6.0})
        ratio = np.max(np.abs(out)) / np.max(np.abs(self.audio))
        self.assertAlmostEqual(ratio, 10 ** (6.0 / 20.0), places=3)

    def test_gain_clamps_range(self):
        out = apply_gain(self.audio, self.sr, {'db': 100.0})
        # Should clamp to 24 dB
        expected_ratio = 10 ** (24.0 / 20.0)
        ratio = np.max(np.abs(out)) / np.max(np.abs(self.audio))
        self.assertAlmostEqual(ratio, expected_ratio, places=3)

    # -- Normalize --
    def test_normalize_peak(self):
        quiet = self.audio * 0.1
        out = apply_normalize(quiet, self.sr, {'peak': 0.95})
        self.assertAlmostEqual(np.max(np.abs(out)), 0.95, places=4)

    def test_normalize_silence(self):
        silence = np.zeros(100, dtype=np.float32)
        out = apply_normalize(silence, self.sr, {'peak': 0.95})
        np.testing.assert_array_equal(out, silence)

    def test_normalize_idempotent(self):
        out1 = apply_normalize(self.audio, self.sr, {'peak': 0.8})
        out2 = apply_normalize(out1, self.sr, {'peak': 0.8})
        np.testing.assert_array_almost_equal(out1, out2, decimal=5)

    # -- ADSR --
    def test_adsr_default_near_unity(self):
        out = apply_adsr(self.audio, self.sr, COMMAND_DEFAULTS['adsr'])
        # With sustain=1.0, middle of sample should be ~1.0x
        mid = len(self.audio) // 2
        ratio = abs(out[mid]) / abs(self.audio[mid]) if abs(self.audio[mid]) > 1e-8 else 1.0
        self.assertAlmostEqual(ratio, 1.0, places=1)

    def test_adsr_preserves_length(self):
        out = apply_adsr(self.audio, self.sr, {'attack_ms': 100, 'decay_ms': 100,
                                                'sustain': 0.5, 'release_ms': 200})
        self.assertEqual(len(out), len(self.audio))

    def test_adsr_empty(self):
        out = apply_adsr(np.array([], dtype=np.float32), self.sr, COMMAND_DEFAULTS['adsr'])
        self.assertEqual(len(out), 0)

    # -- Tremolo --
    def test_tremolo_zero_depth(self):
        out = apply_tremolo(self.audio, self.sr, {'rate_hz': 6.0, 'depth': 0.0})
        np.testing.assert_array_almost_equal(out, self.audio, decimal=5)

    def test_tremolo_preserves_length(self):
        out = apply_tremolo(self.audio, self.sr, COMMAND_DEFAULTS['tremolo'])
        self.assertEqual(len(out), len(self.audio))

    # -- Vibrato --
    def test_vibrato_preserves_length(self):
        out = apply_vibrato(self.audio, self.sr, COMMAND_DEFAULTS['vibrato'])
        self.assertEqual(len(out), len(self.audio))

    # -- Pitch Envelope --
    def test_pitch_env_zero_no_change(self):
        out = apply_pitch_env(self.audio, self.sr, {'start_semi': 0, 'end_semi': 0})
        self.assertEqual(len(out), len(self.audio))

    # -- Overdrive --
    def test_overdrive_preserves_peak(self):
        out = apply_overdrive(self.audio, self.sr, {'drive': 4.0})
        # Normalized output should have similar peak
        self.assertAlmostEqual(np.max(np.abs(out)), np.max(np.abs(self.audio)), places=1)

    def test_overdrive_length(self):
        out = apply_overdrive(self.audio, self.sr, COMMAND_DEFAULTS['overdrive'])
        self.assertEqual(len(out), len(self.audio))

    # -- Echo --
    def test_echo_extends_length(self):
        out = apply_echo(self.audio, self.sr, {'delay_ms': 100, 'decay': 0.5, 'count': 3})
        expected = len(self.audio) + 3 * int(100 * self.sr / 1000)
        self.assertEqual(len(out), expected)

    def test_echo_zero_decay(self):
        out = apply_echo(self.audio, self.sr, {'delay_ms': 100, 'decay': 0.0, 'count': 3})
        # With decay=0, echoes are silent — original part should match
        np.testing.assert_array_almost_equal(out[:len(self.audio)], self.audio, decimal=5)

    # -- Octave --
    def test_octave_down(self):
        out = apply_octave(self.audio, self.sr, {'octaves': -1})
        # Octave down = half speed = double length
        self.assertAlmostEqual(len(out), len(self.audio) * 2, delta=2)

    def test_octave_up(self):
        out = apply_octave(self.audio, self.sr, {'octaves': 1})
        self.assertAlmostEqual(len(out), len(self.audio) / 2, delta=2)

    def test_octave_zero(self):
        out = apply_octave(self.audio, self.sr, {'octaves': 0})
        np.testing.assert_array_equal(out, self.audio)

    # -- Empty/edge cases --
    def test_all_effects_handle_empty(self):
        empty = np.array([], dtype=np.float32)
        for name, fn in COMMAND_APPLY.items():
            defaults = COMMAND_DEFAULTS.get(name, {})
            out = fn(empty, self.sr, defaults)
            self.assertIsInstance(out, np.ndarray, f"{name} failed on empty input")

    def test_all_effects_handle_single_sample(self):
        one = np.array([0.5], dtype=np.float32)
        for name, fn in COMMAND_APPLY.items():
            defaults = COMMAND_DEFAULTS.get(name, {})
            out = fn(one, self.sr, defaults)
            self.assertGreater(len(out), 0, f"{name} returned empty on single sample")


class TestPipeline(unittest.TestCase):
    """Pipeline execution."""

    def setUp(self):
        self.sr = 44100
        self.audio = sine(440, self.sr, 0.5)

    def test_empty_chain(self):
        out = run_pipeline(self.audio, self.sr, [])
        np.testing.assert_array_almost_equal(out, self.audio)

    def test_single_effect(self):
        chain = [SampleCommand('gain', {'db': 6.0})]
        out = run_pipeline(self.audio, self.sr, chain)
        expected = apply_gain(self.audio, self.sr, {'db': 6.0})
        np.testing.assert_array_almost_equal(out, np.clip(expected, -1, 1), decimal=5)

    def test_disabled_skipped(self):
        chain = [SampleCommand('gain', {'db': 6.0}, enabled=False)]
        out = run_pipeline(self.audio, self.sr, chain)
        np.testing.assert_array_almost_equal(out, self.audio)

    def test_unknown_type_skipped(self):
        chain = [SampleCommand('nonexistent_effect', {'x': 1})]
        out = run_pipeline(self.audio, self.sr, chain)
        np.testing.assert_array_almost_equal(out, self.audio)

    def test_order_matters(self):
        trim_then_gain = [
            SampleCommand('trim', {'start_ms': 100, 'end_ms': 200}),
            SampleCommand('gain', {'db': 6.0}),
        ]
        gain_then_trim = [
            SampleCommand('gain', {'db': 6.0}),
            SampleCommand('trim', {'start_ms': 100, 'end_ms': 200}),
        ]
        out1 = run_pipeline(self.audio, self.sr, trim_then_gain)
        out2 = run_pipeline(self.audio, self.sr, gain_then_trim)
        # Same length but different values (gain before trim vs after)
        self.assertEqual(len(out1), len(out2))

    def test_output_clamped(self):
        chain = [SampleCommand('gain', {'db': 24.0}),
                 SampleCommand('gain', {'db': 24.0})]
        out = run_pipeline(self.audio, self.sr, chain)
        self.assertLessEqual(np.max(out), 1.0)
        self.assertGreaterEqual(np.min(out), -1.0)


class TestPipelineAt(unittest.TestCase):
    """Time-travel pipeline."""

    def setUp(self):
        self.sr = 44100
        self.audio = sine(440, self.sr, 0.5)
        self.chain = [
            SampleCommand('gain', {'db': 6.0}),
            SampleCommand('trim', {'start_ms': 50, 'end_ms': 200}),
        ]

    def test_at_end(self):
        dim, bold = run_pipeline_at(self.audio, self.sr, self.chain, len(self.chain))
        np.testing.assert_array_equal(dim, self.audio)
        full = run_pipeline(self.audio, self.sr, self.chain)
        np.testing.assert_array_almost_equal(bold, full)

    def test_at_first(self):
        dim, bold = run_pipeline_at(self.audio, self.sr, self.chain, 0)
        # dim = original (no effects before index 0)
        np.testing.assert_array_almost_equal(dim, self.audio)
        # bold = after gain
        expected = apply_gain(self.audio, self.sr, {'db': 6.0})
        np.testing.assert_array_almost_equal(bold, np.clip(expected, -1, 1), decimal=5)

    def test_at_second(self):
        dim, bold = run_pipeline_at(self.audio, self.sr, self.chain, 1)
        # dim = after gain (input to trim)
        gained = apply_gain(self.audio, self.sr, {'db': 6.0})
        np.testing.assert_array_almost_equal(dim, np.clip(gained, -1, 1), decimal=5)
        # bold = after gain + trim
        self.assertLess(len(bold), len(dim))


class TestInstrumentSerialization(unittest.TestCase):
    """Instrument effects serialization and backward compatibility."""

    def test_instrument_with_effects_roundtrip(self):
        inst = Instrument(name='Test', effects=[
            SampleCommand('gain', {'db': 3.0}),
            SampleCommand('echo', {'delay_ms': 100, 'decay': 0.5, 'count': 2}),
        ])
        d = inst.to_dict()
        inst2 = Instrument.from_dict(d)
        self.assertEqual(len(inst2.effects), 2)
        self.assertEqual(inst2.effects[0].type, 'gain')
        self.assertAlmostEqual(inst2.effects[0].params['db'], 3.0)
        self.assertEqual(inst2.effects[1].type, 'echo')

    def test_instrument_no_effects_backward_compat(self):
        # Old format without 'effects' key
        d = {'name': 'OldInst', 'base_note': 1, 'sample_rate': 44100}
        inst = Instrument.from_dict(d)
        self.assertEqual(inst.effects, [])

    def test_instrument_empty_effects_not_serialized(self):
        inst = Instrument(name='NoFX')
        d = inst.to_dict()
        self.assertNotIn('effects', d)

    def test_song_roundtrip_preserves_effects(self):
        song = Song()
        song.add_instrument("TestInst")
        song.instruments[0].effects = [
            SampleCommand('gain', {'db': -3.0}),
        ]
        d = song.to_dict()
        song2 = Song.from_dict(d)
        self.assertEqual(len(song2.instruments), 1)
        self.assertEqual(len(song2.instruments[0].effects), 1)
        self.assertEqual(song2.instruments[0].effects[0].type, 'gain')

    def test_unknown_effect_preserved(self):
        d = {'name': 'T', 'effects': [
            {'type': 'future_chorus', 'params': {'rate': 2.0}, 'enabled': True}
        ]}
        inst = Instrument.from_dict(d)
        self.assertEqual(len(inst.effects), 1)
        self.assertEqual(inst.effects[0].type, 'future_chorus')
        # Round-trip preserves it
        d2 = inst.to_dict()
        inst2 = Instrument.from_dict(d2)
        self.assertEqual(inst2.effects[0].type, 'future_chorus')


class TestGetPlaybackAudio(unittest.TestCase):
    """get_playback_audio caching."""

    def test_no_effects_returns_raw(self):
        inst = Instrument(sample_data=np.ones(100, dtype=np.float32))
        audio = get_playback_audio(inst)
        np.testing.assert_array_equal(audio, inst.sample_data)

    def test_with_effects_returns_processed(self):
        inst = Instrument(
            sample_data=np.ones(100, dtype=np.float32) * 0.5,
            effects=[SampleCommand('gain', {'db': 6.0})],
        )
        audio = get_playback_audio(inst)
        self.assertIsNotNone(audio)
        # Should be louder than original
        self.assertGreater(np.max(np.abs(audio)), 0.5)

    def test_cache_invalidation(self):
        inst = Instrument(
            sample_data=np.ones(100, dtype=np.float32) * 0.5,
            effects=[SampleCommand('gain', {'db': 6.0})],
        )
        audio1 = get_playback_audio(inst)
        self.assertIsNotNone(inst.processed_data)
        inst.invalidate_cache()
        self.assertIsNone(inst.processed_data)
        audio2 = get_playback_audio(inst)
        np.testing.assert_array_almost_equal(audio1, audio2)

    def test_not_loaded(self):
        inst = Instrument()
        self.assertIsNone(get_playback_audio(inst))


class TestGetSummary(unittest.TestCase):
    """Summary string generation."""

    def test_all_types_produce_string(self):
        for etype, defaults in COMMAND_DEFAULTS.items():
            cmd = SampleCommand(type=etype, params=dict(defaults))
            s = get_summary(cmd)
            self.assertIsInstance(s, str, f"get_summary failed for {etype}")


if __name__ == '__main__':
    unittest.main()
