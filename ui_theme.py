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
            dpg.add_theme_style(dpg.mvStyleVar_FrameRounding, 6)
            dpg.add_theme_style(dpg.mvStyleVar_WindowRounding, 8)
            dpg.add_theme_style(dpg.mvStyleVar_PopupRounding, 8)
            dpg.add_theme_style(dpg.mvStyleVar_ScrollbarRounding, 6)
            dpg.add_theme_style(dpg.mvStyleVar_GrabRounding, 6)
            dpg.add_theme_style(dpg.mvStyleVar_TabRounding, 6)
            dpg.add_theme_style(dpg.mvStyleVar_FramePadding, 10, 6)  # Spacious padding
            dpg.add_theme_style(dpg.mvStyleVar_ItemSpacing, 10, 8)   # Spacious spacing
    
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
    
    # Path to embedded font
    base_dir = os.path.dirname(os.path.abspath(__file__))
    font_path = os.path.join(base_dir, "assets", "fonts", "font.ttf")
    
    with dpg.font_registry():
        if os.path.exists(font_path):
            # Load font with size 20 (larger than default ~13)
            with dpg.font(font_path, 20) as default_font:
                # Add extra characters if needed
                dpg.add_font_range_hint(dpg.mvFontRangeHint_Default)
            dpg.bind_font(default_font)
        else:
            print(f"Warning: Embedded font not found at {font_path}, using default.")
