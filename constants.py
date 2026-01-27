"""Atari Sample Tracker - Constants (v3.0)"""

# === LIMITS ===
MAX_CHANNELS = 3
MAX_OCTAVES = 3  # Changed from 4
MAX_NOTES = MAX_OCTAVES * 12  # 36 notes
MAX_VOLUME = 15
MAX_INSTRUMENTS = 128
MAX_PATTERNS = 256
MAX_ROWS = 256
MAX_SONGLINES = 256

# === DEFAULTS ===
DEFAULT_SPEED = 6
DEFAULT_LENGTH = 64
DEFAULT_OCTAVE = 2
DEFAULT_STEP = 1
VISIBLE_ROWS = 16

# === TIMING ===
PAL_HZ = 50
NTSC_HZ = 60

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
    """Convert note number to string (e.g., 'C-2')."""
    if note == 0:
        return "---"
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
COL_FOCUS = (80, 140, 240)
COL_CH = [(255, 100, 100), (100, 255, 120), (100, 160, 255)]
COL_INACTIVE = (60, 60, 70)  # Color for inactive/muted channels

# === WINDOW ===
WIN_WIDTH = 1400
WIN_HEIGHT = 900
ROW_HEIGHT = 28

# === APP INFO ===
APP_NAME = "Atari Sample Tracker"
APP_VERSION = "3.0"
PROJECT_EXT = ".pvq"
BINARY_EXT = ".pvg"
