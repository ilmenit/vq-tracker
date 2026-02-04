# -*- coding: utf-8 -*-
"""
POKEY VQ Tracker - Version Information

Central location for all version-related constants.
Update this file when releasing new versions.
"""

# =============================================================================
# VERSION INFORMATION
# =============================================================================

# Semantic version components
VERSION_MAJOR = 0
VERSION_MINOR = 9
VERSION_PATCH = 0

# Version stage: "alpha", "beta", "rc", "release"
VERSION_STAGE = "beta"
VERSION_STAGE_NUM = 1  # e.g., beta 1, beta 2, rc1, rc2

# Full version string
if VERSION_STAGE == "release":
    VERSION = f"{VERSION_MAJOR}.{VERSION_MINOR}.{VERSION_PATCH}"
else:
    VERSION = f"{VERSION_MAJOR}.{VERSION_MINOR}.{VERSION_PATCH}-{VERSION_STAGE}.{VERSION_STAGE_NUM}"

# Human-readable version for display
VERSION_DISPLAY = f"Beta {VERSION_STAGE_NUM}"

# Build date (updated manually or by CI)
BUILD_DATE = "2025-02"

# =============================================================================
# APPLICATION INFO
# =============================================================================

APP_NAME = "POKEY VQ Tracker"
APP_AUTHOR = "Atari Community"
APP_DESCRIPTION = "Sample-based music tracker for Atari XL/XE"

# Full application title with version
APP_TITLE = f"{APP_NAME} {VERSION_DISPLAY}"

# =============================================================================
# FILE FORMAT VERSION
# =============================================================================

# Project file format version (increment when format changes incompatibly)
FORMAT_VERSION = 2

# Minimum supported format version for loading
MIN_FORMAT_VERSION = 1

# =============================================================================
# COMPATIBILITY
# =============================================================================

# Python version requirements
PYTHON_MIN_VERSION = (3, 8)

# Target platforms
SUPPORTED_PLATFORMS = ["Windows", "macOS", "Linux"]

# =============================================================================
# UTILITY FUNCTIONS
# =============================================================================

def get_version_info() -> dict:
    """Get version information as a dictionary."""
    return {
        "version": VERSION,
        "version_display": VERSION_DISPLAY,
        "major": VERSION_MAJOR,
        "minor": VERSION_MINOR,
        "patch": VERSION_PATCH,
        "stage": VERSION_STAGE,
        "stage_num": VERSION_STAGE_NUM,
        "build_date": BUILD_DATE,
        "app_name": APP_NAME,
        "format_version": FORMAT_VERSION,
    }


def check_python_version() -> bool:
    """Check if current Python version meets requirements."""
    import sys
    return sys.version_info >= PYTHON_MIN_VERSION


def get_version_string() -> str:
    """Get formatted version string for display."""
    return f"{APP_NAME} {VERSION_DISPLAY} ({VERSION})"


# =============================================================================
# MODULE EXPORTS
# =============================================================================

__version__ = VERSION
__all__ = [
    'VERSION', 'VERSION_DISPLAY', 'VERSION_MAJOR', 'VERSION_MINOR', 'VERSION_PATCH',
    'VERSION_STAGE', 'VERSION_STAGE_NUM', 'BUILD_DATE',
    'APP_NAME', 'APP_AUTHOR', 'APP_DESCRIPTION', 'APP_TITLE',
    'FORMAT_VERSION', 'MIN_FORMAT_VERSION',
    'get_version_info', 'check_python_version', 'get_version_string',
]


if __name__ == "__main__":
    # Print version info when run directly
    print(get_version_string())
    print(f"Format version: {FORMAT_VERSION}")
    print(f"Build date: {BUILD_DATE}")
