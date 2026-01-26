"""
Atari Sample Tracker - UI Theme
Theme setup and color definitions.
"""

import dearpygui.dearpygui as dpg
from constants import COLORS

def setup_theme():
    """Setup Dear PyGui theme."""
    with dpg.theme() as theme:
        with dpg.theme_component(dpg.mvAll):
            # Backgrounds
            dpg.add_theme_color(dpg.mvThemeCol_WindowBg, COLORS['bg_dark'])
            dpg.add_theme_color(dpg.mvThemeCol_ChildBg, COLORS['bg_medium'])
            dpg.add_theme_color(dpg.mvThemeCol_PopupBg, COLORS['bg_medium'])
            
            # Frames
            dpg.add_theme_color(dpg.mvThemeCol_FrameBg, COLORS['bg_light'])
            dpg.add_theme_color(dpg.mvThemeCol_FrameBgHovered, COLORS['highlight'])
            dpg.add_theme_color(dpg.mvThemeCol_FrameBgActive, COLORS['accent_blue'])
            
            # Title
            dpg.add_theme_color(dpg.mvThemeCol_TitleBg, COLORS['bg_medium'])
            dpg.add_theme_color(dpg.mvThemeCol_TitleBgActive, COLORS['accent_blue'])
            
            # Buttons
            dpg.add_theme_color(dpg.mvThemeCol_Button, COLORS['bg_light'])
            dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered, COLORS['highlight'])
            dpg.add_theme_color(dpg.mvThemeCol_ButtonActive, COLORS['accent_blue'])
            
            # Headers
            dpg.add_theme_color(dpg.mvThemeCol_Header, COLORS['bg_light'])
            dpg.add_theme_color(dpg.mvThemeCol_HeaderHovered, COLORS['highlight'])
            dpg.add_theme_color(dpg.mvThemeCol_HeaderActive, COLORS['accent_blue'])
            
            # Text
            dpg.add_theme_color(dpg.mvThemeCol_Text, COLORS['text'])
            dpg.add_theme_color(dpg.mvThemeCol_TextDisabled, COLORS['text_dim'])
            
            # Border
            dpg.add_theme_color(dpg.mvThemeCol_Border, COLORS['border'])
            
            # Scrollbar
            dpg.add_theme_color(dpg.mvThemeCol_ScrollbarBg, COLORS['bg_dark'])
            dpg.add_theme_color(dpg.mvThemeCol_ScrollbarGrab, COLORS['bg_lighter'])
            dpg.add_theme_color(dpg.mvThemeCol_ScrollbarGrabHovered, COLORS['highlight'])
            
            # Style
            dpg.add_theme_style(dpg.mvStyleVar_FrameRounding, 4)
            dpg.add_theme_style(dpg.mvStyleVar_WindowRounding, 5)
            dpg.add_theme_style(dpg.mvStyleVar_FramePadding, 8, 5)  # Increased padding
            dpg.add_theme_style(dpg.mvStyleVar_ItemSpacing, 8, 6)   # Increased spacing
    
    dpg.bind_theme(theme)
    setup_font()
    
    # Cell themes
    with dpg.theme(tag="th_cursor"):
        with dpg.theme_component(dpg.mvAll):
            dpg.add_theme_color(dpg.mvThemeCol_Button, COLORS['cursor_bg'])
            dpg.add_theme_color(dpg.mvThemeCol_Text, COLORS['cursor'])
    
    with dpg.theme(tag="th_playing"):
        with dpg.theme_component(dpg.mvAll):
            dpg.add_theme_color(dpg.mvThemeCol_Button, COLORS['playing_bg'])
            dpg.add_theme_color(dpg.mvThemeCol_Text, COLORS['playing'])
    
    with dpg.theme(tag="th_note_on"):
        with dpg.theme_component(dpg.mvAll):
            dpg.add_theme_color(dpg.mvThemeCol_Text, COLORS['note_on'])
    
    with dpg.theme(tag="th_note_off"):
        with dpg.theme_component(dpg.mvAll):
            dpg.add_theme_color(dpg.mvThemeCol_Text, COLORS['note_off'])
    
    with dpg.theme(tag="th_muted"):
        with dpg.theme_component(dpg.mvAll):
            dpg.add_theme_color(dpg.mvThemeCol_Button, COLORS['accent_red'])
    
    with dpg.theme(tag="th_solo"):
        with dpg.theme_component(dpg.mvAll):
            dpg.add_theme_color(dpg.mvThemeCol_Button, COLORS['accent_yellow'])
    
    # Default theme (for unbinding - resets to normal button style)
    with dpg.theme(tag="th_default"):
        with dpg.theme_component(dpg.mvAll):
            dpg.add_theme_color(dpg.mvThemeCol_Button, COLORS['bg_light'])

def setup_font():
    """Setup and bind a global font."""
    import os
    
    # Common font paths on Linux
    font_paths = [
        "/usr/share/fonts/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/liberation/LiberationSans-Regular.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/usr/share/fonts/gnu-free/FreeSans.ttf",
    ]
    
    font_path = None
    for path in font_paths:
        if os.path.exists(path):
            font_path = path
            break
            
    with dpg.font_registry():
        if font_path:
            # Load font with size 20 (larger than default ~13)
            with dpg.font(font_path, 20) as default_font:
                # Add extra characters if needed
                dpg.add_font_range_hint(dpg.mvFontRangeHint_Default)
            dpg.bind_font(default_font)
        else:
            print("Warning: No system font found, using default.")
