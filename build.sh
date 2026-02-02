#!/bin/bash
# ============================================================================
# POKEY VQ Tracker - Linux/macOS Build Script
# ============================================================================
# Builds standalone executable using PyInstaller
#
# Requirements:
#   - Python 3.8+ installed
#   - Internet connection (for pip install)
#   - MADS binary in bin/{platform}/mads
#
# Usage:
#   ./build.sh           - Build the application
#   ./build.sh clean     - Clean build directories
#   ./build.sh check     - Check dependencies only
#   ./build.sh install   - Install dependencies only
# ============================================================================

set -e  # Exit on error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Change to script directory
cd "$(dirname "$0")"

echo ""
echo "============================================================"
echo "  POKEY VQ Tracker - Build Script"
echo "============================================================"
echo ""

# Detect platform
detect_platform() {
    case "$(uname -s)" in
        Linux*)
            PLATFORM="linux"
            PLATFORM_DIR="linux_x86_64"
            MADS_BINARY="mads"
            ;;
        Darwin*)
            PLATFORM="macos"
            if [[ "$(uname -m)" == "arm64" ]]; then
                PLATFORM_DIR="macos_aarch64"
            else
                PLATFORM_DIR="macos_x86_64"
            fi
            MADS_BINARY="mads"
            ;;
        *)
            echo -e "${RED}[ERROR] Unsupported platform: $(uname -s)${NC}"
            exit 1
            ;;
    esac
    echo "Platform: $PLATFORM ($(uname -m))"
}

# Find Python
find_python() {
    if command -v python3 &> /dev/null; then
        PYTHON="python3"
    elif command -v python &> /dev/null; then
        PYTHON="python"
    else
        echo -e "${RED}[ERROR] Python not found${NC}"
        echo "Please install Python 3.8+ from https://python.org"
        exit 1
    fi
    
    PYVER=$($PYTHON --version 2>&1 | cut -d' ' -f2)
    echo "Python: $PYVER ($PYTHON)"
}

# Clean build directories
clean() {
    echo "Cleaning build directories..."
    rm -rf build dist
    find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
    echo "Done."
}

# Check dependencies
check_deps() {
    echo ""
    echo "Checking required packages..."
    
    MISSING=""
    
    for pkg in dearpygui numpy scipy sounddevice pydub PyInstaller; do
        if $PYTHON -c "import $pkg" 2>/dev/null; then
            echo -e "  ${GREEN}[OK]${NC} $pkg"
        else
            echo -e "  ${RED}[X]${NC} $pkg - MISSING"
            MISSING="$MISSING $pkg"
        fi
    done
    
    # Check for vq_converter folder (required for VQ conversion)
    echo ""
    echo "Checking VQ converter..."
    if [ -d "vq_converter/pokey_vq" ]; then
        echo -e "  ${GREEN}[OK]${NC} vq_converter folder found"
    else
        echo -e "  ${YELLOW}[?]${NC} vq_converter folder not found"
        echo "      (VQ conversion will not work without it)"
        echo "      Place the vq_converter folder alongside the tracker"
    fi
    
    echo ""
    echo "Checking MADS binary..."
    MADS_PATH="bin/$PLATFORM_DIR/$MADS_BINARY"
    if [ -f "$MADS_PATH" ]; then
        echo -e "  ${GREEN}[OK]${NC} $MADS_PATH"
        # Ensure executable
        chmod +x "$MADS_PATH" 2>/dev/null || true
    else
        echo -e "  ${RED}[X]${NC} $MADS_PATH - MISSING"
        echo ""
        echo "  Download MADS from: http://mads.atari8.info/"
        echo "  Place the binary in: bin/$PLATFORM_DIR/"
        MISSING="$MISSING MADS"
    fi
    
    echo ""
    echo "Checking ASM templates..."
    if [ -f "asm/song_player.asm" ]; then
        echo -e "  ${GREEN}[OK]${NC} asm/ directory found"
    else
        echo -e "  ${RED}[X]${NC} asm/ directory missing"
        MISSING="$MISSING ASM"
    fi
    
    echo ""
    if [ -n "$MISSING" ]; then
        echo "============================================================"
        echo -e "  ${RED}Missing components:${NC}$MISSING"
        echo "============================================================"
        echo ""
        echo "To install Python packages:"
        echo "  pip install dearpygui numpy scipy sounddevice pydub soundfile pyinstaller"
        echo ""
        return 1
    fi
    
    echo "============================================================"
    echo -e "  ${GREEN}All checks passed!${NC}"
    echo "============================================================"
    return 0
}

# Install dependencies
install_deps() {
    echo ""
    echo "Installing dependencies..."
    $PYTHON -m pip install --upgrade pip
    $PYTHON -m pip install dearpygui numpy scipy sounddevice pydub soundfile pyinstaller
    echo ""
    echo "Dependencies installed."
}

# Build executable
build() {
    echo ""
    echo "Installing/updating dependencies..."
    $PYTHON -m pip install --quiet --upgrade dearpygui numpy scipy sounddevice pydub soundfile pyinstaller
    
    echo ""
    echo "Building standalone executable..."
    echo ""
    
    $PYTHON -m PyInstaller tracker.spec --noconfirm --clean
    
    echo ""
    echo "============================================================"
    echo -e "  ${GREEN}BUILD SUCCESSFUL!${NC}"
    echo "============================================================"
    echo ""
    
    if [ "$PLATFORM" = "macos" ] && [ -d "dist/POKEY VQ Tracker.app" ]; then
        echo "  Output: dist/POKEY VQ Tracker.app"
        du -sh "dist/POKEY VQ Tracker.app"
        echo ""
        echo "  To run: open 'dist/POKEY VQ Tracker.app'"
    elif [ -f "dist/POKEY_VQ_Tracker" ]; then
        echo "  Output: dist/POKEY_VQ_Tracker"
        ls -lh "dist/POKEY_VQ_Tracker" | awk '{print "  Size: " $5}'
        echo ""
        echo "  To run: ./dist/POKEY_VQ_Tracker"
    fi
    
    echo ""
}

# Main
detect_platform
find_python

case "${1:-build}" in
    clean)
        clean
        ;;
    check)
        check_deps || exit 1
        ;;
    install)
        install_deps
        ;;
    build|"")
        if check_deps; then
            build
        else
            echo ""
            echo "Please fix the issues above before building."
            exit 1
        fi
        ;;
    *)
        echo "Usage: $0 [clean|check|install|build]"
        echo ""
        echo "  clean   - Remove build directories"
        echo "  check   - Check dependencies only"
        echo "  install - Install Python dependencies"
        echo "  build   - Build standalone executable (default)"
        exit 1
        ;;
esac
