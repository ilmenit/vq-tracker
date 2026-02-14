"""POKEY VQ Tracker - Configurable Keyboard Bindings

Loads keyboard shortcuts from keyboard.json, validates them, and provides
lookup for the keyboard handler.

Design:
- Action shortcuts (playback, file ops, octave selection) are configurable
- Navigation keys (arrows, Tab, PageUp/Down, Home/End) are NOT configurable
- Note input keys (piano layout) are NOT configurable
- Modifier prefixes: Ctrl+, Shift+, Ctrl+Shift+

On load errors: falls back to defaults and logs warnings.
"""

import json
import os
import logging
from typing import Dict, Tuple, Optional, List
from dataclasses import dataclass, field

import runtime

logger = logging.getLogger("tracker.key_config")


# =============================================================================
# KNOWN KEY NAMES  (human-readable → DearPyGUI attribute name)
# =============================================================================
# Resolved to numeric codes at init time via getattr(dpg, attr_name)

_KEY_NAME_TO_DPG_ATTR = {
    # Function keys
    "F1": "mvKey_F1", "F2": "mvKey_F2", "F3": "mvKey_F3", "F4": "mvKey_F4",
    "F5": "mvKey_F5", "F6": "mvKey_F6", "F7": "mvKey_F7", "F8": "mvKey_F8",
    "F9": "mvKey_F9", "F10": "mvKey_F10", "F11": "mvKey_F11", "F12": "mvKey_F12",
    # Letters
    "A": "mvKey_A", "B": "mvKey_B", "C": "mvKey_C", "D": "mvKey_D",
    "E": "mvKey_E", "F": "mvKey_F", "G": "mvKey_G", "H": "mvKey_H",
    "I": "mvKey_I", "J": "mvKey_J", "K": "mvKey_K", "L": "mvKey_L",
    "M": "mvKey_M", "N": "mvKey_N", "O": "mvKey_O", "P": "mvKey_P",
    "Q": "mvKey_Q", "R": "mvKey_R", "S": "mvKey_S", "T": "mvKey_T",
    "U": "mvKey_U", "V": "mvKey_V", "W": "mvKey_W", "X": "mvKey_X",
    "Y": "mvKey_Y", "Z": "mvKey_Z",
    # Numbers
    "0": "mvKey_0", "1": "mvKey_1", "2": "mvKey_2", "3": "mvKey_3",
    "4": "mvKey_4", "5": "mvKey_5", "6": "mvKey_6", "7": "mvKey_7",
    "8": "mvKey_8", "9": "mvKey_9",
    # Special
    "Space": "mvKey_Spacebar",
    "Enter": "mvKey_Return",
    "Escape": "mvKey_Escape",
    "Tab": "mvKey_Tab",
    "Delete": "mvKey_Delete",
    "Backspace": "mvKey_Back",
    "Insert": "mvKey_Insert",
    "Home": "mvKey_Home",
    "End": "mvKey_End",
    "PageUp": "mvKey_Prior",
    "PageDown": "mvKey_Next",
    "Up": "mvKey_Up",
    "Down": "mvKey_Down",
    "Left": "mvKey_Left",
    "Right": "mvKey_Right",
    # Numpad
    "NumpadEnter": "mvKey_NumPadEnter",
    "NumpadAdd": "mvKey_Add",
    "NumpadSubtract": "mvKey_Subtract",
    "NumpadMultiply": "mvKey_Multiply",
    "Numpad0": "mvKey_NumPad0", "Numpad1": "mvKey_NumPad1",
    "Numpad2": "mvKey_NumPad2", "Numpad3": "mvKey_NumPad3",
    "Numpad4": "mvKey_NumPad4", "Numpad5": "mvKey_NumPad5",
    "Numpad6": "mvKey_NumPad6", "Numpad7": "mvKey_NumPad7",
    "Numpad8": "mvKey_NumPad8", "Numpad9": "mvKey_NumPad9",
    # Punctuation
    "Minus": "mvKey_Minus",
    "OpenBracket": "mvKey_Open_Brace",
    "CloseBracket": "mvKey_Close_Brace",
}

# Build case-insensitive lookup for key names
_KEY_NAME_LOWER = {k.lower(): k for k in _KEY_NAME_TO_DPG_ATTR}


# =============================================================================
# ALL CONFIGURABLE ACTIONS AND THEIR DEFAULTS
# =============================================================================
# Format: action_name → default key combo string
# The defaults use ScreamTracker-style F5=Play Song, F6=Play Pattern

DEFAULT_BINDINGS: Dict[str, str] = {
    # File operations
    "new_project":          "Ctrl+N",
    "open_project":         "Ctrl+O",
    "save_project":         "Ctrl+S",
    "save_project_as":      "Ctrl+Shift+S",
    "undo":                 "Ctrl+Z",
    "redo":                 "Ctrl+Y",
    "copy":                 "Ctrl+C",
    "cut":                  "Ctrl+X",
    "paste":                "Ctrl+V",
    "jump_first_songline":  "Ctrl+Home",
    "jump_last_songline":   "Ctrl+End",
    "step_up":              "Ctrl+Shift+Up",
    "step_down":            "Ctrl+Shift+Down",

    # Octave selection (3 octaves)
    "octave_1":             "F1",
    "octave_2":             "F2",
    "octave_3":             "F3",

    # Playback  (ScreamTracker layout)
    "play_song":            "F5",
    "play_pattern":         "F6",
    "play_from_cursor":     "F7",
    "stop":                 "F8",
    "play_stop_toggle":     "Space",
    "preview_row":          "Enter",

    # Other
    "show_help":            "F12",
}

# Human-readable descriptions for each action (used in help dialog & errors)
ACTION_DESCRIPTIONS: Dict[str, str] = {
    "new_project":          "New project",
    "open_project":         "Open project",
    "save_project":         "Save project",
    "save_project_as":      "Save as",
    "undo":                 "Undo",
    "redo":                 "Redo",
    "copy":                 "Copy cells",
    "cut":                  "Cut cells",
    "paste":                "Paste cells",
    "jump_first_songline":  "First songline",
    "jump_last_songline":   "Last songline",
    "step_up":              "Increase edit step",
    "step_down":            "Decrease edit step",
    "octave_1":             "Octave 1",
    "octave_2":             "Octave 2",
    "octave_3":             "Octave 3",
    "play_song":            "Play song from start",
    "play_pattern":         "Play pattern from start",
    "play_from_cursor":     "Play from cursor",
    "stop":                 "Stop playback",
    "play_stop_toggle":     "Play/stop toggle",
    "preview_row":          "Preview current row",
    "show_help":            "Show keyboard help",
}


# =============================================================================
# PARSED BINDING
# =============================================================================

@dataclass
class KeyBinding:
    """A parsed key binding: action → (key_code, ctrl, shift)."""
    action: str
    key_name: str       # Human-readable key part (e.g. "S", "F5")
    key_code: int       # DPG numeric key code (resolved at init)
    ctrl: bool
    shift: bool
    combo_str: str      # Original string (e.g. "Ctrl+S")


@dataclass
class KeyConfig:
    """Loaded and validated keyboard configuration."""
    bindings: Dict[str, KeyBinding] = field(default_factory=dict)   # action → KeyBinding
    lookup: Dict[tuple, str] = field(default_factory=dict)          # (key_code, ctrl, shift) → action
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    source: str = "defaults"    # "defaults", "keyboard.json", or path

    def get_combo_str(self, action: str) -> str:
        """Get the human-readable key combo for an action."""
        b = self.bindings.get(action)
        return b.combo_str if b else "?"

    def get_action(self, key_code: int, ctrl: bool, shift: bool) -> Optional[str]:
        """Look up action for a key press. Returns action name or None."""
        return self.lookup.get((key_code, ctrl, shift))


# =============================================================================
# CONFIG FILE PATH
# =============================================================================
CONFIG_FILENAME = "keyboard.json"


def _get_config_path() -> str:
    """Get path to keyboard.json (next to the executable/main.py)."""
    return os.path.join(runtime.get_app_dir(), CONFIG_FILENAME)


# =============================================================================
# PARSING
# =============================================================================

def _parse_combo(combo_str: str) -> Tuple[Optional[str], bool, bool, Optional[str]]:
    """Parse a key combo string like 'Ctrl+Shift+F5' into (key_name, ctrl, shift, error).

    Returns (key_name, ctrl, shift, error_message).
    On success error_message is None.
    """
    combo_str = combo_str.strip()
    if not combo_str:
        return None, False, False, "empty key binding"

    parts = [p.strip() for p in combo_str.split("+")]

    ctrl = False
    shift = False
    key_part = None

    for i, part in enumerate(parts):
        lower = part.lower()
        if lower == "ctrl":
            ctrl = True
        elif lower == "shift":
            shift = True
        elif i == len(parts) - 1:
            # Last part should be the key
            key_part = part
        else:
            return None, False, False, f"unknown modifier '{part}' in '{combo_str}'"

    if key_part is None:
        return None, False, False, f"no key specified in '{combo_str}'"

    # Normalize key name via case-insensitive lookup
    canonical = _KEY_NAME_LOWER.get(key_part.lower())
    if canonical is None:
        return None, False, False, f"unknown key '{key_part}' in '{combo_str}'"

    return canonical, ctrl, shift, None


def _resolve_key_code(key_name: str) -> Optional[int]:
    """Resolve key name to DPG numeric code. Returns None if DPG not available."""
    attr_name = _KEY_NAME_TO_DPG_ATTR.get(key_name)
    if attr_name is None:
        return None
    try:
        import dearpygui.dearpygui as dpg
        # Try primary attribute name first
        val = getattr(dpg, attr_name, None)
        if val is not None:
            return val
        # Try alternative names for keys that changed between DPG versions
        try:
            from dpg_keys import DPG_ATTR_ALTERNATIVES
            alternatives = DPG_ATTR_ALTERNATIVES.get(attr_name, ())
            for alt in alternatives:
                val = getattr(dpg, alt, None)
                if val is not None:
                    return val
        except ImportError:
            pass
        return None
    except ImportError:
        # Deterministic fallback for testing without DPG.
        h = 0x811c9dc5  # FNV-1a offset basis (32-bit)
        for b in attr_name.encode():
            h ^= b
            h = (h * 0x01000193) & 0xFFFFFFFF
        return h & 0x7FFFFFFF


# =============================================================================
# LOADING AND VALIDATION
# =============================================================================

def load_config() -> KeyConfig:
    """Load keyboard configuration from keyboard.json.

    If the file doesn't exist, uses defaults silently.
    If the file has errors, uses defaults for broken entries and reports warnings.
    Always returns a valid KeyConfig with all actions bound.
    """
    config = KeyConfig()
    config_path = _get_config_path()

    # Start with defaults
    raw_bindings = dict(DEFAULT_BINDINGS)

    # Try loading JSON
    if os.path.exists(config_path):
        config.source = config_path
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except json.JSONDecodeError as e:
            config.errors.append(f"keyboard.json: JSON parse error: {e}")
            logger.error(f"keyboard.json parse error: {e}")
            config.source = "defaults (keyboard.json has errors)"
            data = {}
        except Exception as e:
            config.errors.append(f"keyboard.json: read error: {e}")
            logger.error(f"keyboard.json read error: {e}")
            config.source = "defaults (keyboard.json unreadable)"
            data = {}

        if isinstance(data, dict):
            bindings_section = data.get("bindings", {})
            if not isinstance(bindings_section, dict):
                config.errors.append(
                    "keyboard.json: 'bindings' must be a JSON object {}")
            else:
                # Check for unknown action names
                for action_name in bindings_section:
                    if action_name.startswith("_"):
                        continue  # Skip comments
                    if action_name not in DEFAULT_BINDINGS:
                        config.warnings.append(
                            f"Unknown action '{action_name}' — ignored. "
                            f"Valid actions: {', '.join(sorted(DEFAULT_BINDINGS.keys()))}")
                    else:
                        val = bindings_section[action_name]
                        if not isinstance(val, str):
                            config.warnings.append(
                                f"Action '{action_name}': value must be a string "
                                f"like \"Ctrl+S\", got {type(val).__name__} — using default")
                        else:
                            raw_bindings[action_name] = val
        else:
            config.errors.append("keyboard.json: root must be a JSON object {}")
    else:
        config.source = "defaults"

    # Parse all bindings
    seen_combos: Dict[str, str] = {}  # combo_str_normalized → action (for collision check)

    for action, combo_str in raw_bindings.items():
        key_name, ctrl, shift, error = _parse_combo(combo_str)

        if error:
            config.warnings.append(
                f"Action '{action}' ({combo_str}): {error} — using default")
            # Fall back to default
            key_name, ctrl, shift, error2 = _parse_combo(DEFAULT_BINDINGS[action])
            combo_str = DEFAULT_BINDINGS[action]
            if error2:
                # Should never happen with our defaults
                config.errors.append(
                    f"INTERNAL: default for '{action}' is also invalid: {error2}")
                continue

        # Resolve to DPG key code
        key_code = _resolve_key_code(key_name)
        if key_code is None:
            config.warnings.append(
                f"Action '{action}': key '{key_name}' could not be resolved — using default")
            key_name, ctrl, shift, _ = _parse_combo(DEFAULT_BINDINGS[action])
            combo_str = DEFAULT_BINDINGS[action]
            key_code = _resolve_key_code(key_name)
            if key_code is None:
                continue

        # Check for collisions
        norm_key = _normalize_combo(key_name, ctrl, shift)
        # Use normalized form for display (fixes raw casing like "ctrl+f5" → "Ctrl+F5")
        combo_str = norm_key
        if norm_key in seen_combos:
            other_action = seen_combos[norm_key]
            config.errors.append(
                f"KEY COLLISION: '{action}' and '{other_action}' both use "
                f"{combo_str}. '{action}' will be ignored — fix keyboard.json!")
            continue

        seen_combos[norm_key] = action

        binding = KeyBinding(
            action=action,
            key_name=key_name,
            key_code=key_code,
            ctrl=ctrl,
            shift=shift,
            combo_str=combo_str,
        )
        config.bindings[action] = binding
        config.lookup[(key_code, ctrl, shift)] = action

    # Check for missing actions (actions that had collisions and were dropped)
    for action in DEFAULT_BINDINGS:
        if action not in config.bindings:
            config.warnings.append(
                f"Action '{action}' has no binding (collision or error)")

    # Log results
    if config.errors:
        for e in config.errors:
            logger.error(f"[KEY CONFIG] {e}")
    if config.warnings:
        for w in config.warnings:
            logger.warning(f"[KEY CONFIG] {w}")

    n = len(config.bindings)
    logger.info(f"Key config loaded: {n} bindings from {config.source}")
    if config.errors:
        logger.info(f"  {len(config.errors)} error(s), {len(config.warnings)} warning(s)")

    return config


def _normalize_combo(key_name: str, ctrl: bool, shift: bool) -> str:
    """Normalize combo for collision detection."""
    parts = []
    if ctrl:
        parts.append("Ctrl")
    if shift:
        parts.append("Shift")
    parts.append(key_name)
    return "+".join(parts)


# =============================================================================
# DEFAULT CONFIG FILE GENERATION
# =============================================================================

def generate_default_config() -> str:
    """Generate default keyboard.json content."""
    config = {
        "_comment": "POKEY VQ Tracker - Keyboard Configuration",
        "_format": "Action names mapped to key combos. Modifiers: Ctrl+, Shift+, Ctrl+Shift+",
        "_note": "Delete this file to reset to defaults. See docs for valid key names.",
        "_valid_keys": "F1-F12, A-Z, 0-9, Space, Enter, Escape, Tab, Delete, Backspace, "
                       "Insert, Home, End, PageUp, PageDown, Up, Down, Left, Right, "
                       "Minus, OpenBracket, CloseBracket, Numpad0-9, NumpadEnter, "
                       "NumpadAdd, NumpadSubtract, NumpadMultiply",
        "bindings": {}
    }
    # Group bindings with comments
    groups = [
        ("_comment_file", "--- File Operations ---"),
        ("new_project", None), ("open_project", None),
        ("save_project", None), ("save_project_as", None),
        ("undo", None), ("redo", None),
        ("copy", None), ("cut", None), ("paste", None),
        ("_comment_nav", "--- Navigation ---"),
        ("jump_first_songline", None), ("jump_last_songline", None),
        ("step_up", None), ("step_down", None),
        ("_comment_oct", "--- Octave Selection ---"),
        ("octave_1", None), ("octave_2", None),
        ("octave_3", None),
        ("_comment_play", "--- Playback (ScreamTracker layout) ---"),
        ("play_song", None), ("play_pattern", None),
        ("play_from_cursor", None), ("stop", None),
        ("play_stop_toggle", None), ("preview_row", None),
        ("_comment_other", "--- Other ---"),
        ("show_help", None),
    ]

    for key, _ in groups:
        if key.startswith("_comment"):
            config["bindings"][key] = _
        elif key in DEFAULT_BINDINGS:
            config["bindings"][key] = DEFAULT_BINDINGS[key]

    return json.dumps(config, indent=4)


def ensure_config_file():
    """Create keyboard.json with defaults if it doesn't exist."""
    path = _get_config_path()
    if not os.path.exists(path):
        try:
            with open(path, 'w', encoding='utf-8') as f:
                f.write(generate_default_config())
            logger.info(f"Created default {CONFIG_FILENAME}")
        except Exception as e:
            logger.warning(f"Could not create {CONFIG_FILENAME}: {e}")


# =============================================================================
# MODULE-LEVEL STATE
# =============================================================================

# Loaded config (populated by init())
_config: Optional[KeyConfig] = None


def init():
    """Initialize key config. Call once at startup after DPG is available."""
    global _config
    ensure_config_file()
    _config = load_config()
    return _config


def get_config() -> KeyConfig:
    """Get current key config (initializes on first call)."""
    global _config
    if _config is None:
        _config = load_config()
    return _config


def get_action(key_code: int, ctrl: bool, shift: bool) -> Optional[str]:
    """Quick lookup: key press → action name."""
    return get_config().get_action(key_code, ctrl, shift)


def get_combo_str(action: str) -> str:
    """Get display string for an action's key binding."""
    return get_config().get_combo_str(action)


def get_errors() -> List[str]:
    """Get any errors from loading config."""
    return get_config().errors


def get_warnings() -> List[str]:
    """Get any warnings from loading config."""
    return get_config().warnings
