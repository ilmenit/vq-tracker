# -*- coding: utf-8 -*-
"""
Runtime utilities for detecting bundled vs development mode.

When running as a PyInstaller bundle:
- sys._MEIPASS points to the extracted bundle temp directory
- sys.executable points to the bundled executable

When running from source:
- sys._MEIPASS doesn't exist
- sys.executable points to Python interpreter
"""

import os
import sys
import platform


def is_bundled() -> bool:
    """Check if running as a PyInstaller bundle."""
    return getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS')


def get_bundle_dir() -> str:
    """Get the directory containing bundled resources.
    
    Returns:
        When bundled: Path to extracted bundle temp directory
        When dev: Path to the source directory (where this file is)
    """
    if is_bundled():
        return sys._MEIPASS
    else:
        return os.path.dirname(os.path.abspath(__file__))


def get_app_dir() -> str:
    """Get the application directory (where the executable/main.py lives).
    
    Returns:
        When bundled: Directory containing the executable
        When dev: Directory containing main.py
    """
    if is_bundled():
        return os.path.dirname(sys.executable)
    else:
        return os.path.dirname(os.path.abspath(__file__))


def get_resource_path(relative_path: str) -> str:
    """Get absolute path to a resource file.
    
    Args:
        relative_path: Path relative to the bundle/source directory
        
    Returns:
        Absolute path to the resource
    """
    return os.path.join(get_bundle_dir(), relative_path)


def get_asm_dir() -> str:
    """Get path to assembly templates directory.
    
    ASM templates are NOT bundled - they should be distributed alongside 
    the executable. This allows users to modify the player ASM files.
    """
    # Always look next to the executable, not in the bundle
    return os.path.join(get_app_dir(), "asm")


def get_bin_dir() -> str:
    """Get path to bin directory containing MADS and other tools.
    
    bin/ is NOT bundled - it should be distributed alongside the executable.
    This allows users to provide their own MADS binary.
    """
    # Always look next to the executable, not in the bundle
    return os.path.join(get_app_dir(), "bin")


def get_platform_bin_dir() -> str:
    """Get path to platform-specific bin directory.
    
    Returns:
        Path to bin/linux_x86_64, bin/macos_aarch64, bin/windows_x86_64, etc.
    """
    system = platform.system()
    machine = platform.machine().lower()
    
    if system == "Linux":
        plat_dir = "linux_x86_64"
    elif system == "Darwin":
        # Apple Silicon vs Intel
        plat_dir = "macos_aarch64" if "arm" in machine or "aarch" in machine else "macos_x86_64"
    elif system == "Windows":
        plat_dir = "windows_x86_64"
    else:
        plat_dir = ""
    
    if plat_dir:
        return os.path.join(get_bin_dir(), plat_dir)
    return get_bin_dir()


def get_mads_path() -> str:
    """Get path to MADS assembler for current platform.
    
    Returns:
        Path to mads executable, or None if not found
    """
    system = platform.system()
    binary = "mads.exe" if system == "Windows" else "mads"
    
    # Try platform-specific directory first
    plat_path = os.path.join(get_platform_bin_dir(), binary)
    if os.path.isfile(plat_path):
        return plat_path
    
    # Try root bin directory
    root_path = os.path.join(get_bin_dir(), binary)
    if os.path.isfile(root_path):
        return root_path
    
    return None


def get_python_executable() -> str:
    """Get Python executable for subprocess calls.
    
    When bundled, we can't use sys.executable for running Python code.
    Instead, we need to either:
    1. Import modules directly (preferred)
    2. Use a separate bundled Python
    
    Returns:
        sys.executable (which is the bundled exe when frozen)
    """
    return sys.executable


# Debug info
if __name__ == "__main__":
    print(f"Is bundled: {is_bundled()}")
    print(f"Bundle dir: {get_bundle_dir()}")
    print(f"App dir: {get_app_dir()}")
    print(f"ASM dir: {get_asm_dir()}")
    print(f"Bin dir: {get_bin_dir()}")
    print(f"Platform bin dir: {get_platform_bin_dir()}")
    print(f"MADS path: {get_mads_path()}")
    print(f"Python executable: {get_python_executable()}")
