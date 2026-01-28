#!/bin/bash

echo "=========================================="
echo "  PokeyVQ Development Setup (Linux/Mac)"
echo "=========================================="

# Check for Python 3
if ! command -v python3 &> /dev/null; then
    echo "Error: python3 could not be found."
    exit 1
fi

# Create Venv
if [ ! -d ".venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv .venv
else
    echo "Virtual environment already exists."
fi

# Activate
echo "Activating .venv..."
source .venv/bin/activate

# Install
echo "Installing dependencies..."
pip install -r requirements.txt

echo ""
echo "=========================================="
echo "  Setup Complete!"
echo "  To start the GUI:"
echo "    source .venv/bin/activate"
echo "    python3 -m pokey_vq.gui"
echo "=========================================="
