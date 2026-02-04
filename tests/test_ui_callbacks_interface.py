"""Tests for ui_callbacks_interface.py - UICallbacks dataclass.

Ensures the typed callback interface works correctly.
"""
import sys
import os
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ui_callbacks_interface import UICallbacks, _noop


class TestUICallbacks(unittest.TestCase):
    """Tests for UICallbacks."""

    def test_default_noop(self):
        """All callbacks should default to no-ops that don't crash."""
        cb = UICallbacks()
        # These should all succeed silently
        cb.refresh_all()
        cb.refresh_editor()
        cb.show_status("test")
        cb.show_error("title", "message")
        cb.update_title()

    def test_custom_callback(self):
        """Custom callbacks should be called correctly."""
        calls = []
        cb = UICallbacks(
            show_status=lambda msg: calls.append(msg),
            refresh_all=lambda: calls.append("refresh"),
        )
        cb.show_status("hello")
        cb.refresh_all()
        self.assertEqual(calls, ["hello", "refresh"])

    def test_replace_callback(self):
        """Callbacks can be replaced after construction."""
        cb = UICallbacks()
        calls = []
        cb.refresh_editor = lambda: calls.append("editor")
        cb.refresh_editor()
        self.assertEqual(calls, ["editor"])

    def test_noop_is_callable(self):
        """_noop should be callable with any args/kwargs."""
        self.assertIsNone(_noop())
        self.assertIsNone(_noop(1, 2, 3))
        self.assertIsNone(_noop(key="value"))

    def test_set_ui_callbacks_mutates_in_place(self):
        """set_ui_callbacks must mutate the existing object, not replace it.
        
        This is critical because all ops modules do `from ops.base import ui`
        which creates local references. If set_ui_callbacks replaced the object,
        those references would go stale and still point to the default no-ops.
        """
        # Simulate what ops modules do at import time
        original_instance = UICallbacks()
        local_ref = original_instance  # like `from ops.base import ui`
        
        # Simulate set_ui_callbacks mutating in-place
        calls = []
        new_callbacks = UICallbacks(
            show_status=lambda msg: calls.append(msg),
        )
        from dataclasses import fields
        for f in fields(UICallbacks):
            setattr(original_instance, f.name, getattr(new_callbacks, f.name))
        
        # The local reference should see the updated callback
        local_ref.show_status("test")
        self.assertEqual(calls, ["test"])
        self.assertIs(local_ref, original_instance)  # Same object


if __name__ == '__main__':
    unittest.main()
