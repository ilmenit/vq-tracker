"""POKEY VQ Tracker — Sample Editor Commands

Pure-function DSP effects and registry system for the non-destructive
sample editing pipeline. Each effect is a function:

    (audio: np.ndarray, sample_rate: int, params: dict) → np.ndarray

Input/output are 1D float32 arrays, nominally ±1.0.
"""
from dataclasses import dataclass, field
from typing import Dict, Callable, List
import numpy as np


# =============================================================================
# SampleCommand — one effect in the chain
# =============================================================================

@dataclass
class SampleCommand:
    type: str           # registry key: "trim", "gain", "adsr", etc.
    params: dict = field(default_factory=dict)
    enabled: bool = True

    def to_dict(self) -> dict:
        return {
            'type': self.type,
            'params': dict(self.params),
            'enabled': self.enabled,
        }

    @classmethod
    def from_dict(cls, d: dict) -> 'SampleCommand':
        return cls(
            type=d.get('type', ''),
            params=d.get('params', {}),
            enabled=d.get('enabled', True),
        )


# =============================================================================
# Effect functions
# =============================================================================

def apply_trim(audio, sr, params):
    start = int(params.get('start_ms', 0) * sr / 1000)
    end_ms = params.get('end_ms', 0)
    end = len(audio) if end_ms <= 0 else int(end_ms * sr / 1000)
    start = max(0, min(start, len(audio)))
    end = max(start, min(end, len(audio)))
    return audio[start:end].copy() if end > start else audio[:1].copy()


def apply_reverse(audio, sr, params):
    return audio[::-1].copy()


def apply_gain(audio, sr, params):
    db = np.clip(params.get('db', 0.0), -24.0, 24.0)
    return audio * np.float32(10.0 ** (db / 20.0))


def apply_normalize(audio, sr, params):
    if len(audio) == 0:
        return audio.copy()
    peak = np.clip(params.get('peak', 0.95), 0.1, 1.0)
    max_val = np.max(np.abs(audio))
    if max_val > 1e-8:
        return audio * np.float32(peak / max_val)
    return audio.copy()


def apply_adsr(audio, sr, params):
    n = len(audio)
    if n == 0:
        return audio.copy()

    a_ms = max(0, params.get('attack_ms', 10.0))
    d_ms = max(0, params.get('decay_ms', 50.0))
    sus = np.clip(params.get('sustain', 1.0), 0.0, 1.0)
    r_ms = max(0, params.get('release_ms', 100.0))

    a_samp = int(a_ms * sr / 1000)
    d_samp = int(d_ms * sr / 1000)
    r_samp = int(r_ms * sr / 1000)

    total_adr = a_samp + d_samp + r_samp
    if total_adr > n:
        # Proportionally shrink to fit
        scale = n / total_adr if total_adr > 0 else 0
        a_samp = int(a_samp * scale)
        d_samp = int(d_samp * scale)
        r_samp = n - a_samp - d_samp

    s_samp = n - a_samp - d_samp - r_samp

    env = np.ones(n, dtype=np.float32)

    # Attack: cosine ramp 0 → 1
    if a_samp > 0:
        env[:a_samp] = 0.5 - 0.5 * np.cos(np.linspace(0, np.pi, a_samp, dtype=np.float32))

    # Decay: cosine ramp 1 → sustain
    if d_samp > 0:
        d_start = a_samp
        env[d_start:d_start + d_samp] = sus + (1.0 - sus) * (
            0.5 + 0.5 * np.cos(np.linspace(0, np.pi, d_samp, dtype=np.float32)))

    # Sustain
    if s_samp > 0:
        s_start = a_samp + d_samp
        env[s_start:s_start + s_samp] = sus

    # Release: cosine ramp sustain → 0
    if r_samp > 0:
        r_start = n - r_samp
        env[r_start:] = sus * (0.5 + 0.5 * np.cos(
            np.linspace(0, np.pi, r_samp, dtype=np.float32)))

    return audio * env


def apply_tremolo(audio, sr, params):
    n = len(audio)
    if n == 0:
        return audio.copy()
    rate = np.clip(params.get('rate_hz', 6.0), 0.5, 30.0)
    depth = np.clip(params.get('depth', 0.4), 0.0, 1.0)
    t = np.arange(n, dtype=np.float32) / sr
    mod = np.float32(1.0 - depth) + np.float32(depth) * np.sin(
        np.float32(2 * np.pi * rate) * t)
    return audio * mod


def apply_vibrato(audio, sr, params):
    n = len(audio)
    if n == 0:
        return audio.copy()
    rate = np.clip(params.get('rate_hz', 5.0), 0.5, 15.0)
    depth_cents = np.clip(params.get('depth_cents', 20.0), 1.0, 100.0)
    max_delay = sr * (2 ** (depth_cents / 1200.0) - 1) / rate
    t = np.arange(n, dtype=np.float64) / sr
    offset = max_delay * np.sin(2 * np.pi * rate * t)
    read_pos = np.arange(n, dtype=np.float64) + offset
    read_pos = np.clip(read_pos, 0, n - 1)
    idx = read_pos.astype(np.int64)
    frac = (read_pos - idx).astype(np.float32)
    idx_next = np.minimum(idx + 1, n - 1)
    return audio[idx] * (1 - frac) + audio[idx_next] * frac


def apply_pitch_env(audio, sr, params):
    n = len(audio)
    if n == 0:
        return audio.copy()
    start_semi = np.clip(params.get('start_semi', 0.0), -24.0, 24.0)
    end_semi = np.clip(params.get('end_semi', 0.0), -24.0, 24.0)
    semitones = np.linspace(start_semi, end_semi, n, dtype=np.float64)
    ratios = 2.0 ** (semitones / 12.0)
    # Integrate phase to get read positions
    phase = np.cumsum(ratios)
    phase = phase / phase[-1] * (n - 1) if phase[-1] > 0 else np.arange(n, dtype=np.float64)
    phase = np.clip(phase, 0, n - 1)
    idx = phase.astype(np.int64)
    frac = (phase - idx).astype(np.float32)
    idx_next = np.minimum(idx + 1, n - 1)
    return audio[idx] * (1 - frac) + audio[idx_next] * frac


def apply_overdrive(audio, sr, params):
    drive = np.clip(params.get('drive', 4.0), 1.0, 20.0)
    driven = np.tanh(audio * np.float32(drive))
    norm = np.float32(np.tanh(drive))
    return driven / norm if norm > 1e-8 else driven


def apply_echo(audio, sr, params):
    delay_ms = np.clip(params.get('delay_ms', 120.0), 10, 1000)
    decay = np.clip(params.get('decay', 0.5), 0.0, 0.9)
    count = int(np.clip(params.get('count', 3), 1, 10))
    delay_samp = int(delay_ms * sr / 1000)
    out_len = len(audio) + delay_samp * count
    out = np.zeros(out_len, dtype=np.float32)
    out[:len(audio)] = audio
    for i in range(1, count + 1):
        offset = delay_samp * i
        amp = np.float32(decay ** i)
        end = min(offset + len(audio), out_len)
        out[offset:end] += audio[:end - offset] * amp
    return out


def apply_octave(audio, sr, params):
    """Transpose by whole octaves via resampling."""
    n = len(audio)
    if n == 0:
        return audio.copy()
    octaves = int(np.clip(params.get('octaves', -1), -3, 3))
    if octaves == 0:
        return audio.copy()
    ratio = 2.0 ** octaves
    out_len = max(1, int(n / ratio))
    read_pos = np.linspace(0, n - 1, out_len, dtype=np.float64)
    idx = read_pos.astype(np.int64)
    frac = (read_pos - idx).astype(np.float32)
    idx_next = np.minimum(idx + 1, n - 1)
    return audio[idx] * (1 - frac) + audio[idx_next] * frac


# =============================================================================
# Registries
# =============================================================================

COMMAND_APPLY: Dict[str, Callable] = {
    'trim':      apply_trim,
    'reverse':   apply_reverse,
    'gain':      apply_gain,
    'normalize': apply_normalize,
    'adsr':      apply_adsr,
    'tremolo':   apply_tremolo,
    'vibrato':   apply_vibrato,
    'pitch_env': apply_pitch_env,
    'overdrive': apply_overdrive,
    'echo':      apply_echo,
    'octave':    apply_octave,
}

COMMAND_DEFAULTS: Dict[str, dict] = {
    'trim':      {'start_ms': 0.0, 'end_ms': 0.0},
    'reverse':   {},
    'gain':      {'db': 0.0},
    'normalize': {'peak': 0.95},
    'adsr':      {'attack_ms': 10.0, 'decay_ms': 50.0,
                  'sustain': 1.0, 'release_ms': 100.0},
    'tremolo':   {'rate_hz': 6.0, 'depth': 0.4},
    'vibrato':   {'rate_hz': 5.0, 'depth_cents': 20.0},
    'pitch_env': {'start_semi': 0.0, 'end_semi': 0.0},
    'overdrive': {'drive': 4.0},
    'echo':      {'delay_ms': 120.0, 'decay': 0.5, 'count': 3},
    'octave':    {'octaves': -1},
}

COMMAND_LABELS: Dict[str, str] = {
    'trim': 'Trim',          'reverse': 'Reverse',
    'gain': 'Gain',          'normalize': 'Normalize',
    'adsr': 'ADSR Envelope', 'tremolo': 'Tremolo',
    'vibrato': 'Vibrato',    'pitch_env': 'Pitch Envelope',
    'overdrive': 'Overdrive','echo': 'Echo',
    'octave': 'Octave',
}

# Toolbar button labels (short)
COMMAND_TOOLBAR: Dict[str, str] = {
    'trim': 'Trim',   'reverse': 'Rev',
    'gain': 'Gain',   'normalize': 'Norm',
    'adsr': 'ADSR',   'tremolo': 'Trem',
    'vibrato': 'Vib',  'pitch_env': 'Pitch',
    'overdrive': 'OD', 'echo': 'Echo',
    'octave': 'Octa',
}

# Toolbar button order with group spacing
TOOLBAR_ORDER = [
    'trim', 'reverse', None,       # editing (None = spacer)
    'gain', 'normalize', 'adsr', None,  # amplitude
    'tremolo', 'vibrato', 'pitch_env', None,  # modulation
    'overdrive', 'echo', 'octave',  # effects
]


def get_summary(cmd: SampleCommand) -> str:
    """Return compact summary string for chain list display."""
    p = cmd.params
    t = cmd.type
    if t == 'trim':
        end_str = f"{p.get('end_ms', 0):.0f}" if p.get('end_ms', 0) > 0 else "end"
        return f"{p.get('start_ms', 0):.0f} – {end_str} ms"
    elif t == 'reverse':
        return ""
    elif t == 'gain':
        db = p.get('db', 0.0)
        return f"{db:+.1f} dB"
    elif t == 'normalize':
        return f"peak {p.get('peak', 0.95):.2f}"
    elif t == 'adsr':
        return (f"{p.get('attack_ms', 10):.0f}/{p.get('decay_ms', 50):.0f}/"
                f"{p.get('sustain', 1.0):.1f}/{p.get('release_ms', 100):.0f} ms")
    elif t == 'tremolo':
        return f"{p.get('rate_hz', 6.0):.1f} Hz depth {p.get('depth', 0.4):.1f}"
    elif t == 'vibrato':
        return f"{p.get('rate_hz', 5.0):.1f} Hz ±{p.get('depth_cents', 20):.0f} cents"
    elif t == 'pitch_env':
        return f"{p.get('start_semi', 0):+.0f} → {p.get('end_semi', 0):+.0f} semi"
    elif t == 'overdrive':
        return f"drive {p.get('drive', 4.0):.1f}"
    elif t == 'echo':
        return f"{p.get('delay_ms', 120):.0f}ms ×{p.get('count', 3)} decay {p.get('decay', 0.5):.1f}"
    elif t == 'octave':
        o = p.get('octaves', -1)
        return f"{o:+d} oct"
    return ""
