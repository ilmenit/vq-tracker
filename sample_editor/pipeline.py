"""POKEY VQ Tracker — Sample Editor Pipeline

Runs effect chains and provides processed audio for playback/conversion.
"""
from typing import List, Optional, Tuple
import numpy as np
from sample_editor.commands import SampleCommand, COMMAND_APPLY


def run_pipeline(audio: np.ndarray, sr: int,
                 effects: List[SampleCommand]) -> np.ndarray:
    """Run the full effect chain. Returns processed audio."""
    result = audio.copy()
    for cmd in effects:
        if cmd.enabled and cmd.type in COMMAND_APPLY:
            result = COMMAND_APPLY[cmd.type](result, sr, cmd.params)
    return np.clip(result, -1.0, 1.0)


def run_pipeline_at(audio: np.ndarray, sr: int,
                    effects: List[SampleCommand],
                    index: int) -> Tuple[np.ndarray, np.ndarray]:
    """Run pipeline up to the given index for time-travel display.

    Returns (input_to_effect, output_of_effect).
    If index >= len(effects) (End), returns (original, full_pipeline).
    """
    if index >= len(effects):
        return audio, run_pipeline(audio, sr, effects)

    # Input: run all enabled effects before index
    pre = audio.copy()
    for cmd in effects[:index]:
        if cmd.enabled and cmd.type in COMMAND_APPLY:
            pre = COMMAND_APPLY[cmd.type](pre, sr, cmd.params)

    # Output: apply the selected effect to the input
    post = pre.copy()
    cmd = effects[index]
    if cmd.enabled and cmd.type in COMMAND_APPLY:
        post = COMMAND_APPLY[cmd.type](post, sr, cmd.params)

    return np.clip(pre, -1.0, 1.0), np.clip(post, -1.0, 1.0)


def get_playback_audio(instrument) -> Optional[np.ndarray]:
    """Get audio for playback — processed if effects exist, raw otherwise.

    Lazily computes and caches processed_data on the instrument.
    Skips effects when VQ-converted audio is loaded (already processed).
    """
    if not instrument.is_loaded():
        return None

    if not instrument.effects:
        return instrument.sample_data

    # When VQ-converted samples are active, don't re-process through effects.
    # The VQ converter already received effects-processed audio.
    try:
        from state import state as app_state
        if app_state.vq.use_converted:
            return instrument.sample_data
    except (ImportError, AttributeError):
        pass

    if instrument.processed_data is None:
        instrument.processed_data = run_pipeline(
            instrument.sample_data, instrument.sample_rate,
            instrument.effects)
    return instrument.processed_data
