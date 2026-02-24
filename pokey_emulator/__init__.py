"""
pokey_emulator — Cycle-accurate POKEY chip emulator + VQ sample player

Ported from ASAP (Another Slight Atari Player) by Piotr Fusik.
Original: Copyright (C) 2010-2026 Piotr Fusik, GPLv2+

Public API:
    PokeyPair       — Core emulator (register writes → PCM output)
    VQPlayer        — High-level player: loads VQ data, runs song, produces audio
    render_vq_wav   — One-call offline rendering to WAV file
"""

from pokey_emulator.pokey import (
    PokeyChannel, Pokey, PokeyPair,
    NEVER_CYCLE, PAL_CLOCK, NTSC_CLOCK,
    PAL_CYCLES_PER_FRAME, NTSC_CYCLES_PER_FRAME,
    FORMAT_U8, FORMAT_S16LE, FORMAT_S16BE,
    COMPRESSED_SUMS,
)
from pokey_emulator.vq_player import (
    VQPlayer, ChannelState, SongData, InstrumentData, render_vq_wav,
)

__all__ = [
    'PokeyPair', 'Pokey', 'PokeyChannel',
    'VQPlayer', 'ChannelState', 'SongData', 'InstrumentData',
    'render_vq_wav',
    'NEVER_CYCLE', 'PAL_CLOCK', 'NTSC_CLOCK',
    'PAL_CYCLES_PER_FRAME', 'NTSC_CYCLES_PER_FRAME',
    'COMPRESSED_SUMS',
]
