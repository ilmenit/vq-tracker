"""Tests for key_config.py - configurable keyboard bindings.

Covers:
- Combo string parsing
- Default bindings are all valid
- Collision detection
- Unknown action/key handling
- JSON error handling
- Config file round-trip
"""
import sys
import os
import json
import tempfile
import shutil
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Mock dearpygui before importing key_config
import types
dpg_mock = types.ModuleType('dearpygui')
dpg_inner = types.ModuleType('dearpygui.dearpygui')
# Assign fake key codes for all mvKey_ attributes used by key_config
_fake_codes = {}
_counter = [300]
def _fake_code(name):
    _counter[0] += 1
    _fake_codes[name] = _counter[0]
    return _counter[0]

for attr in [
    'mvKey_F1', 'mvKey_F2', 'mvKey_F3', 'mvKey_F4', 'mvKey_F5', 'mvKey_F6',
    'mvKey_F7', 'mvKey_F8', 'mvKey_F9', 'mvKey_F10', 'mvKey_F11', 'mvKey_F12',
    'mvKey_A', 'mvKey_B', 'mvKey_C', 'mvKey_D', 'mvKey_E', 'mvKey_F',
    'mvKey_G', 'mvKey_H', 'mvKey_I', 'mvKey_J', 'mvKey_K', 'mvKey_L',
    'mvKey_M', 'mvKey_N', 'mvKey_O', 'mvKey_P', 'mvKey_Q', 'mvKey_R',
    'mvKey_S', 'mvKey_T', 'mvKey_U', 'mvKey_V', 'mvKey_W', 'mvKey_X',
    'mvKey_Y', 'mvKey_Z',
    'mvKey_0', 'mvKey_1', 'mvKey_2', 'mvKey_3', 'mvKey_4', 'mvKey_5',
    'mvKey_6', 'mvKey_7', 'mvKey_8', 'mvKey_9',
    'mvKey_Spacebar', 'mvKey_Return', 'mvKey_Escape', 'mvKey_Tab',
    'mvKey_Delete', 'mvKey_Back', 'mvKey_Insert',
    'mvKey_Home', 'mvKey_End', 'mvKey_Prior', 'mvKey_Next',
    'mvKey_Up', 'mvKey_Down', 'mvKey_Left', 'mvKey_Right',
    'mvKey_NumPadEnter', 'mvKey_Add', 'mvKey_Subtract', 'mvKey_Multiply',
    'mvKey_NumPad0', 'mvKey_NumPad1', 'mvKey_NumPad2', 'mvKey_NumPad3',
    'mvKey_NumPad4', 'mvKey_NumPad5', 'mvKey_NumPad6', 'mvKey_NumPad7',
    'mvKey_NumPad8', 'mvKey_NumPad9',
    'mvKey_Minus', 'mvKey_Open_Brace', 'mvKey_Close_Brace',
]:
    setattr(dpg_inner, attr, _fake_code(attr))

dpg_mock.dearpygui = dpg_inner
sys.modules['dearpygui'] = dpg_mock
sys.modules['dearpygui.dearpygui'] = dpg_inner

import key_config


class TestParseCombo(unittest.TestCase):
    """Test _parse_combo() string parsing."""

    def test_simple_key(self):
        key, ctrl, shift, err = key_config._parse_combo("F5")
        self.assertIsNone(err)
        self.assertEqual(key, "F5")
        self.assertFalse(ctrl)
        self.assertFalse(shift)

    def test_ctrl_key(self):
        key, ctrl, shift, err = key_config._parse_combo("Ctrl+S")
        self.assertIsNone(err)
        self.assertEqual(key, "S")
        self.assertTrue(ctrl)
        self.assertFalse(shift)

    def test_ctrl_shift_key(self):
        key, ctrl, shift, err = key_config._parse_combo("Ctrl+Shift+S")
        self.assertIsNone(err)
        self.assertEqual(key, "S")
        self.assertTrue(ctrl)
        self.assertTrue(shift)

    def test_shift_key(self):
        key, ctrl, shift, err = key_config._parse_combo("Shift+Tab")
        self.assertIsNone(err)
        self.assertEqual(key, "Tab")
        self.assertFalse(ctrl)
        self.assertTrue(shift)

    def test_case_insensitive(self):
        key, ctrl, shift, err = key_config._parse_combo("ctrl+shift+f5")
        self.assertIsNone(err)
        self.assertEqual(key, "F5")
        self.assertTrue(ctrl)
        self.assertTrue(shift)

    def test_spaces_stripped(self):
        key, ctrl, shift, err = key_config._parse_combo("  Ctrl + Home  ")
        self.assertIsNone(err)
        self.assertEqual(key, "Home")
        self.assertTrue(ctrl)

    def test_empty_string(self):
        _, _, _, err = key_config._parse_combo("")
        self.assertIsNotNone(err)
        self.assertIn("empty", err)

    def test_unknown_key(self):
        _, _, _, err = key_config._parse_combo("Ctrl+FooBar")
        self.assertIsNotNone(err)
        self.assertIn("unknown key", err.lower())

    def test_unknown_modifier(self):
        _, _, _, err = key_config._parse_combo("Alt+F5")
        self.assertIsNotNone(err)
        self.assertIn("unknown modifier", err.lower())

    def test_modifier_only(self):
        _, _, _, err = key_config._parse_combo("Ctrl+Shift")
        # "Shift" is the last token so it's treated as a key name, not a modifier
        # But "Shift" is not in _KEY_NAME_TO_DPG_ATTR, so it should fail
        # Actually, let me think: Shift is recognized as a modifier, and there's
        # no key after it. The code would see Shift as a modifier and no key_part.
        # Actually: parts = ["Ctrl", "Shift"]. The loop:
        #   i=0 "Ctrl" -> ctrl=True
        #   i=1 "Shift" -> i == len(parts)-1 -> key_part = "Shift"
        # Then canonical lookup for "shift" -> not in _KEY_NAME_LOWER -> error.
        self.assertIsNotNone(err)

    def test_special_keys(self):
        for name in ("Space", "Enter", "PageUp", "PageDown", "Home", "End",
                      "Delete", "Backspace", "Insert", "Up", "Down",
                      "NumpadEnter", "NumpadAdd"):
            key, ctrl, shift, err = key_config._parse_combo(name)
            self.assertIsNone(err, f"Failed for key '{name}': {err}")
            self.assertEqual(key, name)


class TestDefaultBindingsValid(unittest.TestCase):
    """Every default binding must parse without error."""

    def test_all_defaults_parse(self):
        for action, combo in key_config.DEFAULT_BINDINGS.items():
            key, ctrl, shift, err = key_config._parse_combo(combo)
            self.assertIsNone(err,
                f"Default binding '{action}': '{combo}' failed to parse: {err}")

    def test_all_defaults_resolve(self):
        for action, combo in key_config.DEFAULT_BINDINGS.items():
            key, ctrl, shift, err = key_config._parse_combo(combo)
            self.assertIsNone(err)
            code = key_config._resolve_key_code(key)
            self.assertIsNotNone(code,
                f"Default binding '{action}': key '{key}' failed to resolve")

    def test_no_default_collisions(self):
        seen = {}
        for action, combo in key_config.DEFAULT_BINDINGS.items():
            key, ctrl, shift, _ = key_config._parse_combo(combo)
            norm = key_config._normalize_combo(key, ctrl, shift)
            self.assertNotIn(norm, seen,
                f"Default collision: '{action}' and '{seen.get(norm)}' both use {combo}")
            seen[norm] = action

    def test_action_descriptions_complete(self):
        """Every action must have a description."""
        for action in key_config.DEFAULT_BINDINGS:
            self.assertIn(action, key_config.ACTION_DESCRIPTIONS,
                f"Action '{action}' missing from ACTION_DESCRIPTIONS")


class TestLoadConfig(unittest.TestCase):
    """Test loading config from JSON files."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        # Patch runtime.get_app_dir to use test dir
        self._orig_get_app_dir = key_config.runtime.get_app_dir
        key_config.runtime.get_app_dir = lambda: self.test_dir
        # Reset cached config
        key_config._config = None

    def tearDown(self):
        key_config.runtime.get_app_dir = self._orig_get_app_dir
        key_config._config = None
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def _write_json(self, data):
        path = os.path.join(self.test_dir, "keyboard.json")
        with open(path, 'w') as f:
            json.dump(data, f)

    def test_defaults_when_no_file(self):
        """No keyboard.json → use defaults, no errors."""
        cfg = key_config.load_config()
        self.assertEqual(len(cfg.errors), 0)
        self.assertEqual(len(cfg.bindings), len(key_config.DEFAULT_BINDINGS))
        self.assertEqual(cfg.source, "defaults")

    def test_valid_override(self):
        """Override play_song from F5 to F9."""
        self._write_json({"bindings": {"play_song": "F9"}})
        cfg = key_config.load_config()
        self.assertEqual(cfg.bindings["play_song"].combo_str, "F9")
        self.assertEqual(cfg.bindings["play_song"].key_name, "F9")
        self.assertEqual(len(cfg.errors), 0)

    def test_screamtracker_defaults(self):
        """Default config has F5=play_song, F6=play_pattern (ScreamTracker)."""
        cfg = key_config.load_config()
        self.assertEqual(cfg.bindings["play_song"].combo_str, "F5")
        self.assertEqual(cfg.bindings["play_pattern"].combo_str, "F6")

    def test_collision_detected(self):
        """Two actions mapped to same key → error reported, second ignored."""
        self._write_json({"bindings": {
            "play_song": "F5",
            "play_pattern": "F5",  # collision!
        }})
        cfg = key_config.load_config()
        collision_errors = [e for e in cfg.errors if "COLLISION" in e]
        self.assertTrue(len(collision_errors) > 0,
            "Expected collision error for play_song/play_pattern on F5")

    def test_unknown_action_warned(self):
        """Unknown action name in JSON → warning, not error."""
        self._write_json({"bindings": {"banana_phone": "F9"}})
        cfg = key_config.load_config()
        self.assertTrue(any("banana_phone" in w for w in cfg.warnings))

    def test_unknown_key_warned(self):
        """Invalid key name → warning, fallback to default."""
        self._write_json({"bindings": {"play_song": "BogusKey"}})
        cfg = key_config.load_config()
        self.assertTrue(any("BogusKey" in w or "boguskey" in w.lower()
                           for w in cfg.warnings))
        # Should fall back to default
        self.assertEqual(cfg.bindings["play_song"].combo_str,
                         key_config.DEFAULT_BINDINGS["play_song"])

    def test_non_string_value_warned(self):
        """Non-string binding value → warning, fallback to default."""
        self._write_json({"bindings": {"play_song": 42}})
        cfg = key_config.load_config()
        self.assertTrue(any("string" in w.lower() for w in cfg.warnings))
        self.assertEqual(cfg.bindings["play_song"].combo_str,
                         key_config.DEFAULT_BINDINGS["play_song"])

    def test_malformed_json_error(self):
        """Broken JSON → error, all defaults."""
        path = os.path.join(self.test_dir, "keyboard.json")
        with open(path, 'w') as f:
            f.write("{broken json!!!")
        cfg = key_config.load_config()
        self.assertTrue(len(cfg.errors) > 0)
        self.assertIn("JSON parse error", cfg.errors[0])
        # Should still have all defaults
        self.assertEqual(len(cfg.bindings), len(key_config.DEFAULT_BINDINGS))

    def test_root_not_object_error(self):
        """JSON root is a list → error."""
        path = os.path.join(self.test_dir, "keyboard.json")
        with open(path, 'w') as f:
            json.dump([1, 2, 3], f)
        cfg = key_config.load_config()
        self.assertTrue(any("root must be" in e for e in cfg.errors))

    def test_bindings_not_object_error(self):
        """bindings is a list → error."""
        self._write_json({"bindings": [1, 2, 3]})
        cfg = key_config.load_config()
        self.assertTrue(any("'bindings' must be" in e for e in cfg.errors))

    def test_comment_keys_ignored(self):
        """Keys starting with _ in bindings are silently skipped."""
        self._write_json({"bindings": {
            "_comment": "This is a comment",
            "play_song": "F5",
        }})
        cfg = key_config.load_config()
        self.assertNotIn("_comment", cfg.bindings)
        self.assertEqual(len(cfg.errors), 0)
        # No warning about "_comment" being unknown
        self.assertFalse(any("_comment" in w for w in cfg.warnings))

    def test_partial_override(self):
        """Override only some bindings; rest use defaults."""
        self._write_json({"bindings": {"stop": "F10"}})
        cfg = key_config.load_config()
        self.assertEqual(cfg.bindings["stop"].combo_str, "F10")
        # play_song should still be default F5
        self.assertEqual(cfg.bindings["play_song"].combo_str, "F5")

    def test_lookup_by_key_code(self):
        """get_action returns correct action for key code."""
        cfg = key_config.load_config()
        # Find the key code for play_song (default F5)
        b = cfg.bindings["play_song"]
        action = cfg.get_action(b.key_code, b.ctrl, b.shift)
        self.assertEqual(action, "play_song")

    def test_lookup_miss_returns_none(self):
        """get_action returns None for unbound key."""
        cfg = key_config.load_config()
        action = cfg.get_action(99999, False, False)
        self.assertIsNone(action)


class TestEnsureConfigFile(unittest.TestCase):
    """Test auto-creation of keyboard.json."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self._orig = key_config.runtime.get_app_dir
        key_config.runtime.get_app_dir = lambda: self.test_dir

    def tearDown(self):
        key_config.runtime.get_app_dir = self._orig
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_creates_file_if_missing(self):
        path = os.path.join(self.test_dir, "keyboard.json")
        self.assertFalse(os.path.exists(path))
        key_config.ensure_config_file()
        self.assertTrue(os.path.exists(path))

    def test_created_file_is_valid_json(self):
        key_config.ensure_config_file()
        path = os.path.join(self.test_dir, "keyboard.json")
        with open(path) as f:
            data = json.load(f)
        self.assertIn("bindings", data)
        self.assertIn("play_song", data["bindings"])

    def test_does_not_overwrite_existing(self):
        path = os.path.join(self.test_dir, "keyboard.json")
        with open(path, 'w') as f:
            f.write('{"bindings": {"stop": "F10"}}')
        key_config.ensure_config_file()
        with open(path) as f:
            data = json.load(f)
        # Should not have been overwritten
        self.assertEqual(data["bindings"]["stop"], "F10")


class TestGenerateDefault(unittest.TestCase):
    """Test generate_default_config()."""

    def test_output_is_valid_json(self):
        text = key_config.generate_default_config()
        data = json.loads(text)
        self.assertIn("bindings", data)

    def test_all_actions_present(self):
        text = key_config.generate_default_config()
        data = json.loads(text)
        for action in key_config.DEFAULT_BINDINGS:
            self.assertIn(action, data["bindings"],
                f"Action '{action}' missing from generated config")

    def test_screamtracker_layout(self):
        """Generated default must use F5=play_song, F6=play_pattern."""
        text = key_config.generate_default_config()
        data = json.loads(text)
        self.assertEqual(data["bindings"]["play_song"], "F5")
        self.assertEqual(data["bindings"]["play_pattern"], "F6")


class TestNormalizeCombo(unittest.TestCase):

    def test_no_modifiers(self):
        self.assertEqual(key_config._normalize_combo("F5", False, False), "F5")

    def test_ctrl(self):
        self.assertEqual(key_config._normalize_combo("S", True, False), "Ctrl+S")

    def test_shift(self):
        self.assertEqual(key_config._normalize_combo("Tab", False, True), "Shift+Tab")

    def test_ctrl_shift(self):
        self.assertEqual(key_config._normalize_combo("S", True, True), "Ctrl+Shift+S")


if __name__ == '__main__':
    unittest.main()
