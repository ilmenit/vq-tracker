"""POKEY VQ Tracker - Safe DearPyGUI Key Constants

DPG key constants changed between versions:
  - DPG 1.x used GLFW/Win32 VK codes (mvKey_Prior, mvKey_Next, etc.)
  - DPG 2.0 switched to ImGui key enum (mvKey_PageUp, mvKey_PageDown, etc.)
  - Some keys (grave/tilde, brackets) have inconsistent export names

This module resolves key constants safely at runtime by trying multiple
attribute names.  Both keyboard.py and key_config.py import from here.
"""
import logging

logger = logging.getLogger("tracker.dpg_keys")

# Will be populated by init() after DPG context is created
_keys = {}
_initialized = False


def _resolve(*names):
    """Try multiple DPG attribute names, return first that exists."""
    import dearpygui.dearpygui as dpg
    for name in names:
        val = getattr(dpg, name, None)
        if val is not None:
            return val
    return None


def init():
    """Resolve all key constants. Call once after dpg.create_context()."""
    global _keys, _initialized
    import dearpygui.dearpygui as dpg

    # Keys that have consistent names across DPG versions
    DIRECT_KEYS = [
        'mvKey_A', 'mvKey_B', 'mvKey_C', 'mvKey_D', 'mvKey_E', 'mvKey_F',
        'mvKey_G', 'mvKey_H', 'mvKey_I', 'mvKey_J', 'mvKey_K', 'mvKey_L',
        'mvKey_M', 'mvKey_N', 'mvKey_O', 'mvKey_P', 'mvKey_Q', 'mvKey_R',
        'mvKey_S', 'mvKey_T', 'mvKey_U', 'mvKey_V', 'mvKey_W', 'mvKey_X',
        'mvKey_Y', 'mvKey_Z',
        'mvKey_0', 'mvKey_1', 'mvKey_2', 'mvKey_3', 'mvKey_4',
        'mvKey_5', 'mvKey_6', 'mvKey_7', 'mvKey_8', 'mvKey_9',
        'mvKey_NumPad0', 'mvKey_NumPad1', 'mvKey_NumPad2', 'mvKey_NumPad3',
        'mvKey_NumPad4', 'mvKey_NumPad5', 'mvKey_NumPad6', 'mvKey_NumPad7',
        'mvKey_NumPad8', 'mvKey_NumPad9',
        'mvKey_Add', 'mvKey_Subtract', 'mvKey_Multiply',
        'mvKey_Up', 'mvKey_Down', 'mvKey_Left', 'mvKey_Right',
        'mvKey_Home', 'mvKey_End', 'mvKey_Delete', 'mvKey_Insert',
        'mvKey_Escape', 'mvKey_Spacebar', 'mvKey_Return', 'mvKey_Tab',
        'mvKey_LControl', 'mvKey_RControl', 'mvKey_LShift', 'mvKey_RShift',
        'mvKey_F1', 'mvKey_F2', 'mvKey_F3', 'mvKey_F4', 'mvKey_F5',
        'mvKey_F6', 'mvKey_F7', 'mvKey_F8', 'mvKey_F9', 'mvKey_F10',
        'mvKey_F11', 'mvKey_F12',
    ]

    for name in DIRECT_KEYS:
        val = getattr(dpg, name, None)
        if val is not None:
            _keys[name] = val

    # Keys with version-dependent names (try alternatives)
    FALLBACK_KEYS = {
        # DPG 1.x name           → DPG 2.0 name
        'mvKey_Prior':           ('mvKey_Prior', 'mvKey_PageUp'),
        'mvKey_Next':            ('mvKey_Next', 'mvKey_PageDown'),
        'mvKey_Back':            ('mvKey_Back', 'mvKey_Backspace'),
        'mvKey_Minus':           ('mvKey_Minus',),
        'mvKey_Open_Brace':      ('mvKey_Open_Brace', 'mvKey_LeftBracket'),
        'mvKey_Close_Brace':     ('mvKey_Close_Brace', 'mvKey_RightBracket'),
        'mvKey_NumPadEnter':     ('mvKey_NumPadEnter', 'mvKey_KeypadEnter'),
    }

    for canonical, alternatives in FALLBACK_KEYS.items():
        val = _resolve(*alternatives)
        if val is not None:
            _keys[canonical] = val
        else:
            logger.warning(f"Could not resolve key: {canonical} "
                           f"(tried: {', '.join(alternatives)})")

    # Also store resolved values under ALL tried names for lookups
    for canonical, alternatives in FALLBACK_KEYS.items():
        val = _keys.get(canonical)
        if val is not None:
            for alt in alternatives:
                _keys[alt] = val

    # Grave accent / backtick - try known DPG names and hardcoded values
    grave = _resolve('mvKey_Grave', 'mvKey_GraveAccent')
    if grave is not None:
        _keys['mvKey_Grave'] = grave
    # Also store known hardcoded values for the grave key
    # DPG internal code 606, GLFW code 96
    _keys['_grave_codes'] = set()
    if grave is not None:
        _keys['_grave_codes'].add(grave)
    _keys['_grave_codes'].add(606)
    _keys['_grave_codes'].add(96)

    _initialized = True

    # Log diagnostics
    n = len([k for k in _keys if not k.startswith('_')])
    logger.info(f"Resolved {n} key constants")

    # Log problematic keys specifically
    for key in ['mvKey_Prior', 'mvKey_Next', 'mvKey_F1', 'mvKey_F2', 'mvKey_F3',
                'mvKey_Back', 'mvKey_Open_Brace', 'mvKey_Close_Brace']:
        val = _keys.get(key)
        if val is not None:
            logger.debug(f"  {key} = {val}")
        else:
            logger.warning(f"  {key} = NOT FOUND")


def get(name, default=None):
    """Get a resolved key code by DPG attribute name."""
    return _keys.get(name, default)


def get_grave_codes():
    """Get the set of all possible grave/backtick key codes."""
    return _keys.get('_grave_codes', {606, 96})


def dump_key_codes():
    """Return a formatted string of all resolved key codes for diagnostics."""
    lines = ["Resolved DPG key constants:"]
    important = ['mvKey_F1', 'mvKey_F2', 'mvKey_F3', 'mvKey_F4', 'mvKey_F5',
                 'mvKey_F6', 'mvKey_F7', 'mvKey_F8', 'mvKey_Prior', 'mvKey_Next',
                 'mvKey_Back', 'mvKey_Minus', 'mvKey_Open_Brace', 'mvKey_Close_Brace',
                 'mvKey_NumPadEnter', 'mvKey_Home', 'mvKey_End', 'mvKey_Return']
    for name in important:
        val = _keys.get(name)
        status = str(val) if val is not None else "NOT FOUND"
        lines.append(f"  {name:24s} = {status}")
    lines.append(f"  Grave codes: {get_grave_codes()}")
    return "\n".join(lines)


def build_key_map():
    """Build the key-to-character map using resolved constants.

    Returns dict mapping key_code → character for note input and hex entry.
    """
    import dearpygui.dearpygui as dpg
    km = {}

    # Letters
    for letter in 'abcdefghijklmnopqrstuvwxyz':
        key = get(f'mvKey_{letter.upper()}')
        if key is not None:
            km[key] = letter

    # Digits
    for d in range(10):
        key = get(f'mvKey_{d}')
        if key is not None:
            km[key] = str(d)
        npkey = get(f'mvKey_NumPad{d}')
        if npkey is not None:
            km[npkey] = str(d)

    # Operators and punctuation
    minus = get('mvKey_Minus')
    if minus is not None:
        km[minus] = '-'
    subtract = get('mvKey_Subtract')
    if subtract is not None:
        km[subtract] = '-'
    add = get('mvKey_Add')
    if add is not None:
        km[add] = '+'
    multiply = get('mvKey_Multiply')
    if multiply is not None:
        km[multiply] = '*'

    # Grave/backtick - add ALL known codes
    for code in get_grave_codes():
        km[code] = '`'

    # Equals sign (hardcoded fallbacks for different backends)
    km[602] = '='  # DPG internal
    km[61] = '='   # GLFW

    return km


# ── Convenience aliases for the DPG attribute names used in key_config ──

# Map from human-readable key name → list of DPG attribute names to try
# (used by key_config._resolve_key_code)
DPG_ATTR_ALTERNATIVES = {
    'mvKey_Prior':       ('mvKey_Prior', 'mvKey_PageUp'),
    'mvKey_Next':        ('mvKey_Next', 'mvKey_PageDown'),
    'mvKey_Back':        ('mvKey_Back', 'mvKey_Backspace'),
    'mvKey_Open_Brace':  ('mvKey_Open_Brace', 'mvKey_LeftBracket'),
    'mvKey_Close_Brace': ('mvKey_Close_Brace', 'mvKey_RightBracket'),
    'mvKey_NumPadEnter': ('mvKey_NumPadEnter', 'mvKey_KeypadEnter'),
    'mvKey_Minus':       ('mvKey_Minus',),
}
