"""POKEY VQ Tracker - Constants"""

# === LIMITS ===
MAX_CHANNELS = 3
MAX_OCTAVES = 3  # 3 octaves (C-1 to B-3, indices 0-35)
MAX_NOTES = MAX_OCTAVES * 12  # 36 notes
NOTE_OFF = 255  # Special value for note-off (silence/stop)
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
VQ_RATE_DEFAULT = 5278
VQ_VECTOR_SIZES = [2, 4, 8, 16]  # Must be powers of 2 for ASM optimization
VQ_VECTOR_DEFAULT = 8
VQ_SMOOTHNESS_VALUES = [0, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100]
VQ_SMOOTHNESS_DEFAULT = 0

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
COL_CH = [(255, 100, 100), (100, 255, 120), (100, 160, 255)]
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
