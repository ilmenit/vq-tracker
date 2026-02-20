"""POKEY VQ Tracker - Constants"""

# === LIMITS ===
MAX_CHANNELS = 4
MAX_OCTAVES = 3  # 3 octaves (C-1 to B-3, indices 0-35)
MAX_NOTES = MAX_OCTAVES * 12  # 36 notes
NOTE_OFF = 255  # Special value for note-off (silence/stop)
VOL_CHANGE = 254  # Special value for volume-only change (no retrigger)
MAX_VOLUME = 15
MAX_INSTRUMENTS = 128
MAX_PATTERNS = 256
MAX_ROWS = 254  # Limited to 254 because row $FF (255) is used as end marker in export format
MAX_SONGLINES = 255  # Limited to 255 (8-bit counter, and to allow safe comparison)

# === DEFAULTS ===
DEFAULT_SPEED = 6
DEFAULT_LENGTH = 64
DEFAULT_OCTAVE = 1  # Lowest octave
DEFAULT_STEP = 1
VISIBLE_ROWS = 16

# === TIMING ===
PAL_HZ = 50
NTSC_HZ = 60

# === VQ CONVERSION ===
# POKEY PAL Sample Rates (Hz) - divisor values map to these rates
VQ_RATES = [
    15834, 12667, 10556, 9048, 7917, 7037, 6333, 5757,
    5278, 4872, 4524, 4222, 3958, 3725, 3518, 3333
]
VQ_RATE_DEFAULT = 3958
VQ_VECTOR_SIZES = [2, 4, 8, 16]  # Must be powers of 2 for ASM optimization
VQ_VECTOR_DEFAULT = 8
VQ_SMOOTHNESS_VALUES = [0, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100]
VQ_SMOOTHNESS_DEFAULT = 0

# Memory budget for sample data (bytes)
# Atari memory map with ROM-under-RAM:
#   $2000-$3BFF = code + read-only tables + staging (~6 KB)
#   $3C00-$3FFF = free (charset relocated to $FC00)
#   $4000-$7FFF = bank window (sample audio; or main RAM in 64KB mode)
#   $8000-$CFFF = song data region A (20 KB, banking mode)
#   $D000-$D7FF = hardware I/O (untouchable)
#   $D800-$FBFF = song data region B (9 KB, banking mode)
#   $FC00-$FFFF = relocated charset (CHBASE=$FC)
# Banking mode: song data spans 29KB across regions A+B (split around I/O gap).
# 64KB mode: everything shares $2000-$BFFF (~40KB), charset stays at $E000.
# Fixed overhead: player code, IRQ handler, pitch tables, volume scale, staging vars
# (in banking mode these are placed before $4000, NOT in the song data regions)
FIXED_CODE_OVERHEAD = 3800  # player code + IRQ + pitch tables + volume scale + staging

# === START ADDRESS ===
DEFAULT_START_ADDRESS = 0x2000
MIN_START_ADDRESS = 0x0800     # Below screen RAM
MAX_START_ADDRESS = 0x3F00     # Must be below bank window $4000

# === MEMORY CONFIGURATIONS ===
MEMORY_CONFIGS = [
    ("64 KB",    0,  "No extended RAM. All data in main memory."),
    ("128 KB",   4,  "130XE compatible. 4 banks (64 KB ext)."),
    ("320 KB",  16,  "320KB expansion. 16 banks (256 KB ext)."),
    ("576 KB",  32,  "Rambo/Compy. 32 banks (512 KB ext)."),
    ("1088 KB", 64,  "1MB expansion. 64 banks (1 MB ext)."),
]
MEMORY_CONFIG_NAMES = [m[0] for m in MEMORY_CONFIGS]
DEFAULT_MEMORY_CONFIG = "64 KB"


def estimate_song_data_bytes(n_songlines: int, n_patterns: int,
                              pattern_lengths: list = None,
                              avg_events_per_row: float = 0.5) -> int:
    """Estimate song data size in bytes from song dimensions.
    
    This estimates SONG_DATA.asm size: songline tables, pattern directory,
    and variable-length event data.
    
    Args:
        n_songlines: Number of songlines
        n_patterns: Number of patterns  
        pattern_lengths: List of pattern lengths (if None, assume 64)
        avg_events_per_row: Average events per row (0.3-0.8 typical)
    """
    # Songline tables: SPEED + 4 channel pattern indices
    songline_bytes = 5 * n_songlines
    
    # Pattern directory: LEN + PTR_LO + PTR_HI
    directory_bytes = 3 * n_patterns
    
    # Pattern event data
    if pattern_lengths:
        total_rows = sum(pattern_lengths)
    else:
        total_rows = n_patterns * 64
    
    # Each event: 2-4 bytes (note+row = 2, with inst = 3, with vol = 4)
    # Plus $FF end marker per pattern
    avg_event_size = 2.8  # typical with occasional inst/vol changes
    event_bytes = total_rows * avg_events_per_row * avg_event_size + n_patterns
    
    return int(songline_bytes + directory_bytes + event_bytes)


def estimate_vq_overhead_bytes(n_instruments: int, vector_size: int = 4) -> int:
    """Estimate VQ overhead beyond sample data (indices + raw pages).
    
    This covers VQ_BLOB (codebook), VQ_LO, VQ_HI, and SAMPLE_DIR — 
    data that the converter's "Atari data" number includes but that's
    NOT the sample data the optimizer budgets for.
    
    Actually, the converter's size_bytes DOES include these. But we need
    this to know total address space usage.
    """
    codebook = 256 * vector_size  # VQ_BLOB
    lo_hi = 2 * 1024  # VQ_LO + VQ_HI (conservative upper bound)
    sample_dir = 6 * max(n_instruments, 1)  # 5 tables + MODE
    return codebook + lo_hi + sample_dir


def compute_memory_budget(start_address: int = DEFAULT_START_ADDRESS,
                          memory_config: str = DEFAULT_MEMORY_CONFIG,
                          n_songlines: int = 1,
                          n_patterns: int = 1,
                          pattern_lengths: list = None,
                          n_instruments: int = 1,
                          vector_size: int = 4) -> int:
    """Compute sample data memory budget in bytes.
    
    This is the space available for VQ_INDICES + RAW_SAMPLES — the data
    the optimizer allocates. Everything else (code, song data, codebook,
    sample directory) is subtracted as overhead.
    
    64KB mode:  $C000 - start_address - all_overhead
    Banking:    n_banks × 16384 (sample data lives in bank windows)
    """
    if memory_config != "64 KB":
        for name, n_banks, _ in MEMORY_CONFIGS:
            if name == memory_config:
                return n_banks * 16384
        return 4 * 16384  # fallback to 130XE
    
    total_space = 0xC000 - start_address
    
    song_overhead = estimate_song_data_bytes(
        n_songlines, n_patterns, pattern_lengths)
    vq_overhead = estimate_vq_overhead_bytes(n_instruments, vector_size)
    
    overhead = FIXED_CODE_OVERHEAD + song_overhead + vq_overhead
    
    budget = total_space - overhead
    return max(2048, budget)  # never return less than 2KB

# === FOCUS AREAS ===
FOCUS_SONG = 0
FOCUS_PATTERN = 1
FOCUS_INSTRUMENTS = 2
FOCUS_INFO = 3
FOCUS_EDITOR = 4

# === CELL COLUMNS ===
COL_NOTE = 0
COL_INST = 1
COL_VOL = 2

# === NOTE NAMES ===
NOTE_NAMES = ['C-', 'C#', 'D-', 'D#', 'E-', 'F-', 'F#', 'G-', 'G#', 'A-', 'A#', 'B-']

def note_to_str(note: int) -> str:
    """Convert note number to string (e.g., 'C-2').
    
    Special values:
    - 0 = empty/continue (---)
    - 1-36 = actual notes (C-1 to B-3)
    - 255 = note off (OFF)
    """
    if note == 0:
        return "---"
    if note == NOTE_OFF:
        return "OFF"
    if note == VOL_CHANGE:
        return "V--"
    if note > MAX_NOTES:
        note = MAX_NOTES
    idx = (note - 1) % 12
    octave = ((note - 1) // 12) + 1
    return f"{NOTE_NAMES[idx]}{octave}"

# === PIANO KEY MAPPING ===
# Lower row: Z-M = C-B (base octave)
# S,D,G,H,J = sharps
# Upper row: Q-P = C-E (octave+1)  
# 2,3,5,6,7,9,0 = sharps
NOTE_KEYS = {
    # Base octave (Z-M row)
    'z': 0, 's': 1, 'x': 2, 'd': 3, 'c': 4, 'v': 5,
    'g': 6, 'b': 7, 'h': 8, 'n': 9, 'j': 10, 'm': 11,
    # Octave+1 (Q-P row)
    'q': 12, '2': 13, 'w': 14, '3': 15, 'e': 16, 'r': 17,
    '5': 18, 't': 19, '6': 20, 'y': 21, '7': 22, 'u': 23,
    'i': 24, '9': 25, 'o': 26, '0': 27, 'p': 28,
}

# === COLORS (RGBA) ===
COL_BG = (18, 18, 24)
COL_BG2 = (28, 30, 38)
COL_BG3 = (42, 46, 58)
COL_TEXT = (220, 220, 230)
COL_DIM = (120, 125, 140)
COL_MUTED = (80, 85, 100)
COL_ACCENT = (80, 140, 240)
COL_GREEN = (80, 200, 120)
COL_RED = (240, 80, 80)
COL_YELLOW = (240, 200, 80)
COL_CYAN = (80, 200, 220)
COL_PURPLE = (160, 110, 220)
COL_CURSOR = (100, 160, 255)
COL_CURSOR_BG = (40, 60, 100)
COL_PLAY_BG = (30, 70, 40)
COL_REPEAT_BG = (45, 40, 55)
COL_BORDER = (50, 55, 70)
COL_FOCUS = (100, 180, 255)  # Bright blue for focused panel border
COL_CH = [(255, 100, 100), (100, 255, 120), (100, 160, 255), (240, 200, 80)]
COL_INACTIVE = (60, 60, 70)  # Color for inactive/muted channels

# === WINDOW ===
WIN_WIDTH = 1400
WIN_HEIGHT = 900
ROW_HEIGHT = 28

# === APP INFO ===
# Import from centralized version file
from version import APP_NAME, VERSION_DISPLAY as APP_VERSION, FORMAT_VERSION

PROJECT_EXT = ".pvq"
BINARY_EXT = ".pvg"
