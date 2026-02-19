"""POKEY VQ Tracker — Cell Color Palettes

Provides colored text themes for pattern editor cells.
Each palette defines 16 colors. Palettes can be assigned independently
to note, instrument, and volume columns.

Note column:   color index = (note - 1) % 12    (chromatic)
Instrument column: color index = instrument % 16
Volume column: color index = volume (0–15)
"""
import logging

try:
    import dearpygui.dearpygui as dpg
except ImportError:
    dpg = None

from constants import COL_BG3, NOTE_OFF, VOL_CHANGE

logger = logging.getLogger("tracker.cell_colors")

# ============================================================================
# PALETTE DEFINITIONS — 16 RGB tuples each
# ============================================================================

# Designed for legibility on dark backgrounds (BG ~30-45 lightness).
# All colors have minimum ~150 luminance to stay readable.

PALETTES = {
    # --- Multi-color (16 distinct hues) ---
    "Chromatic": [
        (255, 100, 100),  # 0  red
        (255, 150, 80),   # 1  orange
        (240, 200, 80),   # 2  yellow
        (180, 220, 80),   # 3  lime
        (100, 220, 100),  # 4  green
        (80, 220, 160),   # 5  sea green
        (80, 210, 210),   # 6  cyan
        (80, 180, 240),   # 7  sky blue
        (100, 140, 255),  # 8  blue
        (150, 120, 255),  # 9  indigo
        (190, 110, 240),  # 10 purple
        (230, 100, 200),  # 11 magenta
        (255, 100, 150),  # 12 rose
        (200, 160, 120),  # 13 tan
        (160, 200, 180),  # 14 sage
        (180, 180, 220),  # 15 lavender
    ],
    "Pastel": [
        (240, 160, 160),  # 0  rose
        (240, 180, 140),  # 1  peach
        (230, 210, 140),  # 2  cream
        (190, 220, 150),  # 3  mint
        (150, 220, 170),  # 4  soft green
        (140, 210, 200),  # 5  aqua
        (150, 200, 220),  # 6  powder blue
        (160, 180, 230),  # 7  periwinkle
        (180, 170, 230),  # 8  lilac
        (200, 160, 220),  # 9  orchid
        (220, 160, 200),  # 10 pink
        (230, 170, 180),  # 11 blush
        (210, 190, 160),  # 12 sand
        (180, 200, 170),  # 13 sage
        (170, 200, 200),  # 14 mist
        (200, 190, 210),  # 15 mauve
    ],
    "Neon": [
        (255, 60, 60),    # 0  hot red
        (255, 120, 0),    # 1  blaze orange
        (255, 230, 0),    # 2  electric yellow
        (120, 255, 0),    # 3  neon green
        (0, 255, 120),    # 4  spring green
        (0, 255, 220),    # 5  aqua
        (0, 220, 255),    # 6  electric blue
        (0, 150, 255),    # 7  azure
        (80, 80, 255),    # 8  ultraviolet
        (160, 60, 255),   # 9  violet
        (230, 40, 255),   # 10 magenta
        (255, 40, 180),   # 11 hot pink
        (255, 80, 80),    # 12 scarlet
        (200, 200, 0),    # 13 chartreuse
        (0, 200, 200),    # 14 teal
        (200, 150, 255),  # 15 lavender
    ],
    "Warm": [
        (255, 120, 100),  # 0  coral
        (240, 140, 90),   # 1  burnt orange
        (220, 170, 100),  # 2  amber
        (240, 200, 100),  # 3  gold
        (255, 220, 140),  # 4  light gold
        (240, 200, 160),  # 5  wheat
        (220, 180, 150),  # 6  tan
        (200, 150, 130),  # 7  sienna
        (230, 130, 130),  # 8  salmon
        (250, 150, 150),  # 9  light coral
        (240, 160, 180),  # 10 rose
        (220, 140, 170),  # 11 dusty rose
        (200, 160, 140),  # 12 clay
        (210, 180, 130),  # 13 sand
        (230, 200, 150),  # 14 cream
        (255, 200, 180),  # 15 peach
    ],

    # --- Single-color (uniform) ---
    "White":  [(220, 220, 230)] * 16,
    "Green":  [(100, 220, 120)] * 16,
    "Amber":  [(240, 200, 80)] * 16,
    "Cyan":   [(80, 210, 220)] * 16,
    "Blue":   [(120, 170, 255)] * 16,
    "Pink":   [(240, 140, 180)] * 16,
}

PALETTE_NAMES = ["None"] + list(PALETTES.keys())

# Background colors for the 3 colorable cell states
_BG_NORMAL = COL_BG3           # (42, 46, 58)
_BG_HIGHLIGHT = (35, 40, 55)   # beat marker row
_BG_CURRENT = (30, 38, 55)     # cursor's row (non-cursor cells)

_VARIANTS = {
    "n": _BG_NORMAL,
    "h": _BG_HIGHLIGHT,
    "c": _BG_CURRENT,
}

# Cache of created theme tags
_themes_created = False


def create_cell_color_themes():
    """Create DPG themes for all palette colors. Call once after dpg.create_context()."""
    global _themes_created
    if _themes_created or dpg is None:
        return

    count = 0
    for pal_name, colors in PALETTES.items():
        for ci, color in enumerate(colors):
            # Button themes (for pattern editor cells and song grid)
            for vk, bg in _VARIANTS.items():
                tag = _theme_tag(pal_name, ci, vk)
                if dpg.does_item_exist(tag):
                    continue
                with dpg.theme(tag=tag):
                    with dpg.theme_component(dpg.mvButton):
                        dpg.add_theme_color(dpg.mvThemeCol_Button, bg)
                        dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered, bg)
                        dpg.add_theme_color(dpg.mvThemeCol_ButtonActive, bg)
                        dpg.add_theme_color(dpg.mvThemeCol_Text, color)
                count += 1

            # Combo theme (text color only — for combo dropdowns)
            ctag = _combo_tag(pal_name, ci)
            if not dpg.does_item_exist(ctag):
                with dpg.theme(tag=ctag):
                    with dpg.theme_component(dpg.mvAll):
                        dpg.add_theme_color(dpg.mvThemeCol_Text, color)
                count += 1

    _themes_created = True
    logger.info(f"Created {count} cell color themes")


def _theme_tag(palette: str, index: int, variant: str) -> str:
    """Build a button theme tag string."""
    return f"theme_cc_{palette}_{index}_{variant}"


def _combo_tag(palette: str, index: int) -> str:
    """Build a combo (text-only) theme tag string."""
    return f"theme_ct_{palette}_{index}"


def get_note_color_theme(note: int, palette: str, variant: str = "n"):
    """Get theme tag for a note cell, or None if palette is 'None'.

    Args:
        note: Note value (1-36 = notes, 254 = V--, 255 = OFF, 0 = empty)
        palette: Palette name from PALETTE_NAMES
        variant: "n" = normal bg, "h" = highlight bg, "c" = current row bg
    """
    if palette == "None" or note == 0:
        return None
    if note == NOTE_OFF or note == VOL_CHANGE:
        return None  # Special events keep default color
    index = (note - 1) % 12  # 12 chromatic notes, wrapping
    return _theme_tag(palette, index, variant)


def get_inst_color_theme(instrument: int, has_note: bool, palette: str, variant: str = "n"):
    """Get theme tag for an instrument cell, or None."""
    if palette == "None" or not has_note:
        return None
    index = instrument % 16
    return _theme_tag(palette, index, variant)


def get_vol_color_theme(volume: int, has_note: bool, palette: str, variant: str = "n"):
    """Get theme tag for a volume cell, or None."""
    if palette == "None" or not has_note:
        return None
    index = volume % 16  # volume is 0–15, maps directly
    return _theme_tag(palette, index, variant)


def get_ptn_color_theme(pattern: int, palette: str, variant: str = "n"):
    """Get button theme tag for a pattern number cell (Song grid), or None."""
    if palette == "None":
        return None
    index = pattern % 16
    return _theme_tag(palette, index, variant)


def get_combo_color_theme(value: int, palette: str):
    """Get combo (text-only) theme tag for a value, or None."""
    if palette == "None":
        return None
    index = value % 16
    return _combo_tag(palette, index)
