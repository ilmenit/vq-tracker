"""POKEY VQ Tracker - UI Themes"""
import dearpygui.dearpygui as dpg
from constants import (COL_BG, COL_BG2, COL_BG3, COL_TEXT, COL_DIM, COL_MUTED,
                       COL_ACCENT, COL_GREEN, COL_RED, COL_YELLOW, COL_CYAN,
                       COL_CURSOR_BG, COL_PLAY_BG, COL_REPEAT_BG, COL_BORDER, COL_FOCUS,
                       COL_CH)

def create_themes():
    """Create all UI themes."""
    
    # === GLOBAL THEME ===
    with dpg.theme() as global_theme:
        with dpg.theme_component(dpg.mvAll):
            dpg.add_theme_color(dpg.mvThemeCol_WindowBg, COL_BG)
            dpg.add_theme_color(dpg.mvThemeCol_ChildBg, COL_BG)
            dpg.add_theme_color(dpg.mvThemeCol_PopupBg, COL_BG2)
            dpg.add_theme_color(dpg.mvThemeCol_FrameBg, COL_BG2)
            dpg.add_theme_color(dpg.mvThemeCol_FrameBgHovered, COL_BG3)
            dpg.add_theme_color(dpg.mvThemeCol_FrameBgActive, COL_BG3)
            dpg.add_theme_color(dpg.mvThemeCol_Button, COL_BG2)
            dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered, COL_BG3)
            dpg.add_theme_color(dpg.mvThemeCol_ButtonActive, COL_ACCENT)
            dpg.add_theme_color(dpg.mvThemeCol_Header, COL_BG2)
            dpg.add_theme_color(dpg.mvThemeCol_HeaderHovered, COL_BG3)
            dpg.add_theme_color(dpg.mvThemeCol_HeaderActive, COL_ACCENT)
            dpg.add_theme_color(dpg.mvThemeCol_Text, COL_TEXT)
            dpg.add_theme_color(dpg.mvThemeCol_Border, COL_BORDER)
            dpg.add_theme_color(dpg.mvThemeCol_ScrollbarBg, COL_BG)
            dpg.add_theme_color(dpg.mvThemeCol_ScrollbarGrab, COL_BG3)
            dpg.add_theme_color(dpg.mvThemeCol_CheckMark, COL_ACCENT)
            dpg.add_theme_color(dpg.mvThemeCol_SliderGrab, COL_ACCENT)
            dpg.add_theme_style(dpg.mvStyleVar_FrameRounding, 3)
            dpg.add_theme_style(dpg.mvStyleVar_FramePadding, 6, 4)
            dpg.add_theme_style(dpg.mvStyleVar_ItemSpacing, 8, 4)
            dpg.add_theme_style(dpg.mvStyleVar_ScrollbarSize, 12)
    dpg.bind_theme(global_theme)
    
    # === CELL THEMES ===
    
    # Normal cell (has note)
    with dpg.theme(tag="theme_cell_note"):
        with dpg.theme_component(dpg.mvButton):
            dpg.add_theme_color(dpg.mvThemeCol_Button, COL_BG3)
            dpg.add_theme_color(dpg.mvThemeCol_Text, COL_TEXT)
    
    # Empty cell
    with dpg.theme(tag="theme_cell_empty"):
        with dpg.theme_component(dpg.mvButton):
            dpg.add_theme_color(dpg.mvThemeCol_Button, COL_BG2)
            dpg.add_theme_color(dpg.mvThemeCol_Text, COL_DIM)
    
    # Cursor cell
    with dpg.theme(tag="theme_cell_cursor"):
        with dpg.theme_component(dpg.mvButton):
            dpg.add_theme_color(dpg.mvThemeCol_Button, COL_CURSOR_BG)
            dpg.add_theme_color(dpg.mvThemeCol_Text, (255, 255, 255))
    
    # Playing row
    with dpg.theme(tag="theme_cell_playing"):
        with dpg.theme_component(dpg.mvButton):
            dpg.add_theme_color(dpg.mvThemeCol_Button, COL_PLAY_BG)
            dpg.add_theme_color(dpg.mvThemeCol_Text, COL_GREEN)
    
    # Repeat zone (pattern shorter than max)
    with dpg.theme(tag="theme_cell_repeat"):
        with dpg.theme_component(dpg.mvButton):
            dpg.add_theme_color(dpg.mvThemeCol_Button, COL_REPEAT_BG)
            dpg.add_theme_color(dpg.mvThemeCol_Text, COL_MUTED)
    
    # Selected cell
    with dpg.theme(tag="theme_cell_selected"):
        with dpg.theme_component(dpg.mvButton):
            dpg.add_theme_color(dpg.mvThemeCol_Button, (60, 80, 120))
            dpg.add_theme_color(dpg.mvThemeCol_Text, (255, 255, 255))
    
    # Current row (cursor row highlight, "under" cursor) - darker to not conflict with cursor
    with dpg.theme(tag="theme_cell_current_row"):
        with dpg.theme_component(dpg.mvButton):
            dpg.add_theme_color(dpg.mvThemeCol_Button, (30, 38, 55))  # Much darker blue-ish
            dpg.add_theme_color(dpg.mvThemeCol_Text, (180, 190, 210))
    
    # === CHANNEL THEMES ===
    
    # Inactive channel cell (dimmed)
    with dpg.theme(tag="theme_cell_inactive"):
        with dpg.theme_component(dpg.mvButton):
            dpg.add_theme_color(dpg.mvThemeCol_Button, (30, 30, 35))
            dpg.add_theme_color(dpg.mvThemeCol_Text, (70, 70, 80))
    
    # Default button
    with dpg.theme(tag="theme_button_default"):
        with dpg.theme_component(dpg.mvButton):
            dpg.add_theme_color(dpg.mvThemeCol_Button, COL_BG2)
            dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered, COL_BG3)
    
    # Header button (for column labels - non-interactive look)
    with dpg.theme(tag="theme_header_button"):
        with dpg.theme_component(dpg.mvButton):
            dpg.add_theme_color(dpg.mvThemeCol_Button, COL_BG)  # Match background
            dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered, COL_BG)  # No hover change
            dpg.add_theme_color(dpg.mvThemeCol_ButtonActive, COL_BG)  # No active change
            dpg.add_theme_color(dpg.mvThemeCol_Text, COL_MUTED)  # Dimmed text
    
    # Per-channel colored header buttons (song panel column labels)
    # Also used for pattern editor Note/Ins/Vol column headers
    for ch_idx, ch_color in enumerate(COL_CH):
        with dpg.theme(tag=f"theme_header_ch{ch_idx}"):
            with dpg.theme_component(dpg.mvButton):
                dpg.add_theme_color(dpg.mvThemeCol_Button, COL_BG)
                dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered, COL_BG)
                dpg.add_theme_color(dpg.mvThemeCol_ButtonActive, COL_BG)
                dpg.add_theme_color(dpg.mvThemeCol_Text, ch_color)
                dpg.add_theme_color(dpg.mvThemeCol_TextDisabled, ch_color)
        
        # Song data cell with channel-tinted text (non-cursor, non-playing state)
        # Uses dimmer version of channel color so cursor/playing highlights stand out
        dim_ch = (ch_color[0] * 2 // 3, ch_color[1] * 2 // 3, ch_color[2] * 2 // 3)
        with dpg.theme(tag=f"theme_song_cell_ch{ch_idx}"):
            with dpg.theme_component(dpg.mvButton):
                dpg.add_theme_color(dpg.mvThemeCol_Button, COL_BG2)
                dpg.add_theme_color(dpg.mvThemeCol_Text, dim_ch)
        
        # Song data cell on cursor row but not the focused cell
        with dpg.theme(tag=f"theme_song_cell_ch{ch_idx}_row"):
            with dpg.theme_component(dpg.mvButton):
                dpg.add_theme_color(dpg.mvThemeCol_Button, (30, 38, 55))
                dpg.add_theme_color(dpg.mvThemeCol_Text, ch_color)
    
    # SPD header (yellow-ish label)
    with dpg.theme(tag="theme_header_spd"):
        with dpg.theme_component(dpg.mvButton):
            dpg.add_theme_color(dpg.mvThemeCol_Button, COL_BG)
            dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered, COL_BG)
            dpg.add_theme_color(dpg.mvThemeCol_ButtonActive, COL_BG)
            dpg.add_theme_color(dpg.mvThemeCol_Text, (180, 180, 100))
    
    # === PANEL THEMES ===
    
    # Focused panel border - bright and thick
    with dpg.theme(tag="theme_panel_focused"):
        with dpg.theme_component(dpg.mvChildWindow):
            dpg.add_theme_color(dpg.mvThemeCol_Border, COL_FOCUS)
            dpg.add_theme_style(dpg.mvStyleVar_ChildBorderSize, 3)
    
    # Normal panel border
    with dpg.theme(tag="theme_panel_normal"):
        with dpg.theme_component(dpg.mvChildWindow):
            dpg.add_theme_color(dpg.mvThemeCol_Border, COL_BORDER)
            dpg.add_theme_style(dpg.mvStyleVar_ChildBorderSize, 1)
    
    # Zero-padding container (for aligning channel headers with data columns)
    with dpg.theme(tag="theme_container_nopad"):
        with dpg.theme_component(dpg.mvChildWindow):
            dpg.add_theme_style(dpg.mvStyleVar_WindowPadding, 0, 0)
            dpg.add_theme_style(dpg.mvStyleVar_ChildBorderSize, 0)
            dpg.add_theme_color(dpg.mvThemeCol_ChildBg, (0, 0, 0, 0))
    
    # === TEXT THEMES ===
    
    # Dim text
    with dpg.theme(tag="theme_text_dim"):
        with dpg.theme_component(dpg.mvText):
            dpg.add_theme_color(dpg.mvThemeCol_Text, COL_DIM)
    
    # Accent text
    with dpg.theme(tag="theme_text_accent"):
        with dpg.theme_component(dpg.mvText):
            dpg.add_theme_color(dpg.mvThemeCol_Text, COL_ACCENT)
    
    # Green text
    with dpg.theme(tag="theme_text_green"):
        with dpg.theme_component(dpg.mvText):
            dpg.add_theme_color(dpg.mvThemeCol_Text, COL_GREEN)
    
    # Yellow text
    with dpg.theme(tag="theme_text_yellow"):
        with dpg.theme_component(dpg.mvText):
            dpg.add_theme_color(dpg.mvThemeCol_Text, COL_YELLOW)
    
    # Cyan text
    with dpg.theme(tag="theme_text_cyan"):
        with dpg.theme_component(dpg.mvText):
            dpg.add_theme_color(dpg.mvThemeCol_Text, COL_CYAN)
    
    # === SONG ROW NUMBER THEMES ===
    
    # Normal row number (dim)
    with dpg.theme(tag="theme_song_row_normal"):
        with dpg.theme_component(dpg.mvButton):
            dpg.add_theme_color(dpg.mvThemeCol_Button, (25, 28, 35))
            dpg.add_theme_color(dpg.mvThemeCol_Text, (100, 100, 110))
    
    # Highlighted row number (beat marker - slightly brighter)
    with dpg.theme(tag="theme_song_row_highlight"):
        with dpg.theme_component(dpg.mvButton):
            dpg.add_theme_color(dpg.mvThemeCol_Button, (32, 36, 48))
            dpg.add_theme_color(dpg.mvThemeCol_Text, (130, 130, 150))
    
    # Cursor row number (bright blue)
    with dpg.theme(tag="theme_song_row_cursor"):
        with dpg.theme_component(dpg.mvButton):
            dpg.add_theme_color(dpg.mvThemeCol_Button, (40, 55, 80))
            dpg.add_theme_color(dpg.mvThemeCol_Text, (100, 160, 255))
    
    # Playing row number (green)
    with dpg.theme(tag="theme_song_row_playing"):
        with dpg.theme_component(dpg.mvButton):
            dpg.add_theme_color(dpg.mvThemeCol_Button, (30, 50, 35))
            dpg.add_theme_color(dpg.mvThemeCol_Text, (80, 200, 100))
    
    # Empty/inactive row number
    with dpg.theme(tag="theme_song_row_empty"):
        with dpg.theme_component(dpg.mvButton):
            dpg.add_theme_color(dpg.mvThemeCol_Button, (20, 22, 28))
            dpg.add_theme_color(dpg.mvThemeCol_Text, (50, 50, 60))
    
    # === CELL HIGHLIGHT (beat rows) ===
    
    # Highlighted cell (beat marker row, not cursor/playing)
    with dpg.theme(tag="theme_cell_highlight"):
        with dpg.theme_component(dpg.mvButton):
            dpg.add_theme_color(dpg.mvThemeCol_Button, (35, 40, 55))
            dpg.add_theme_color(dpg.mvThemeCol_Text, COL_TEXT)
    
    # === WARNING/ERROR CELL THEMES ===
    
    # Cell with invalid instrument reference (yellow warning)
    with dpg.theme(tag="theme_cell_warning"):
        with dpg.theme_component(dpg.mvButton):
            dpg.add_theme_color(dpg.mvThemeCol_Button, (60, 50, 25))
            dpg.add_theme_color(dpg.mvThemeCol_Text, COL_YELLOW)
    
    # Cell with error (red)
    with dpg.theme(tag="theme_cell_error"):
        with dpg.theme_component(dpg.mvButton):
            dpg.add_theme_color(dpg.mvThemeCol_Button, (60, 25, 25))
            dpg.add_theme_color(dpg.mvThemeCol_Text, COL_RED)
    
    # === INSTRUMENT THEMES (VQ conversion state) ===
    
    # Instrument not converted (normal/gray)
    with dpg.theme(tag="theme_inst_normal"):
        with dpg.theme_component(dpg.mvButton):
            dpg.add_theme_color(dpg.mvThemeCol_Button, COL_BG2)
            dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered, (42, 46, 55))
            dpg.add_theme_color(dpg.mvThemeCol_ButtonActive, (50, 55, 65))
            dpg.add_theme_color(dpg.mvThemeCol_Text, COL_TEXT)
    
    # Instrument converted (green tint)
    with dpg.theme(tag="theme_inst_converted"):
        with dpg.theme_component(dpg.mvButton):
            dpg.add_theme_color(dpg.mvThemeCol_Button, (25, 45, 35))
            dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered, (32, 58, 45))
            dpg.add_theme_color(dpg.mvThemeCol_ButtonActive, (40, 70, 55))
            dpg.add_theme_color(dpg.mvThemeCol_Text, (180, 230, 180))
    
    # Instrument selected + not converted
    with dpg.theme(tag="theme_inst_selected"):
        with dpg.theme_component(dpg.mvButton):
            dpg.add_theme_color(dpg.mvThemeCol_Button, COL_CURSOR_BG)
            dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered, (55, 70, 100))
            dpg.add_theme_color(dpg.mvThemeCol_ButtonActive, (65, 80, 110))
            dpg.add_theme_color(dpg.mvThemeCol_Text, (255, 255, 255))
    
    # Instrument selected + converted
    with dpg.theme(tag="theme_inst_selected_converted"):
        with dpg.theme_component(dpg.mvButton):
            dpg.add_theme_color(dpg.mvThemeCol_Button, (40, 70, 55))
            dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered, (48, 85, 65))
            dpg.add_theme_color(dpg.mvThemeCol_ButtonActive, (55, 100, 75))
            dpg.add_theme_color(dpg.mvThemeCol_Text, (200, 255, 200))
    
    # === VQ CONVERT BUTTON THEMES ===
    
    # Convert button normal (needs conversion)
    with dpg.theme(tag="theme_btn_convert"):
        with dpg.theme_component(dpg.mvButton):
            dpg.add_theme_color(dpg.mvThemeCol_Button, (35, 70, 50))
            dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered, (45, 90, 65))
            dpg.add_theme_color(dpg.mvThemeCol_ButtonActive, (55, 110, 80))
            dpg.add_theme_color(dpg.mvThemeCol_Text, (180, 255, 180))
    
    # Green button (BUILD ready, CONVERT done)
    with dpg.theme(tag="theme_btn_green"):
        with dpg.theme_component(dpg.mvButton):
            dpg.add_theme_color(dpg.mvThemeCol_Button, (30, 80, 45))
            dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered, (40, 100, 60))
            dpg.add_theme_color(dpg.mvThemeCol_ButtonActive, (50, 120, 75))
            dpg.add_theme_color(dpg.mvThemeCol_Text, (150, 255, 150))
    
    # Disabled/gray button
    with dpg.theme(tag="theme_btn_disabled"):
        with dpg.theme_component(dpg.mvButton):
            dpg.add_theme_color(dpg.mvThemeCol_Button, (40, 40, 45))
            dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered, (45, 45, 50))
            dpg.add_theme_color(dpg.mvThemeCol_ButtonActive, (50, 50, 55))
            dpg.add_theme_color(dpg.mvThemeCol_Text, (100, 100, 110))
    
    # Blinking button - bright phase (green highlight)
    with dpg.theme(tag="theme_btn_blink_bright"):
        with dpg.theme_component(dpg.mvButton):
            dpg.add_theme_color(dpg.mvThemeCol_Button, (45, 100, 60))
            dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered, (55, 120, 75))
            dpg.add_theme_color(dpg.mvThemeCol_ButtonActive, (65, 140, 90))
            dpg.add_theme_color(dpg.mvThemeCol_Text, (200, 255, 200))
    
    # Blinking button - dim phase (grayish)
    with dpg.theme(tag="theme_btn_blink_dim"):
        with dpg.theme_component(dpg.mvButton):
            dpg.add_theme_color(dpg.mvThemeCol_Button, (50, 55, 50))
            dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered, (60, 70, 60))
            dpg.add_theme_color(dpg.mvThemeCol_ButtonActive, (70, 85, 70))
            dpg.add_theme_color(dpg.mvThemeCol_Text, (150, 160, 150))

    # Effects indicator - active (has effects)
    with dpg.theme(tag="theme_fx_active"):
        with dpg.theme_component(dpg.mvButton):
            dpg.add_theme_color(dpg.mvThemeCol_Button, (35, 55, 80))
            dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered, (45, 70, 100))
            dpg.add_theme_color(dpg.mvThemeCol_ButtonActive, (55, 85, 120))
            dpg.add_theme_color(dpg.mvThemeCol_Text, (160, 200, 255))

    # === CELL COLOR PALETTES ===
    from cell_colors import create_cell_color_themes
    create_cell_color_themes()


def get_inst_theme(is_selected: bool, is_converted: bool) -> str:
    """Get theme for instrument button."""
    if is_selected:
        return "theme_inst_selected_converted" if is_converted else "theme_inst_selected"
    return "theme_inst_converted" if is_converted else "theme_inst_normal"


def get_cell_theme(is_cursor: bool, is_playing: bool, is_selected: bool, 
                   is_repeat: bool, has_note: bool, is_inactive: bool = False) -> str:
    """Get appropriate theme for a cell."""
    if is_inactive and not is_cursor:
        return "theme_cell_inactive"
    if is_cursor:
        return "theme_cell_cursor"
    if is_selected:
        return "theme_cell_selected"
    if is_playing:
        return "theme_cell_playing"
    if is_repeat:
        return "theme_cell_repeat"
    if has_note:
        return "theme_cell_note"
    return "theme_cell_empty"
