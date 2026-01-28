"""
PokeyVQ GUI Entry Point (Wrapper)
Redirects to the modular GUI implementation in pokey_vq/gui/
"""
import sys
import os

# Ensure we can import the package
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pokey_vq.gui.app import PokeyApp

def main():
    app = PokeyApp()
    app.run()

if __name__ == "__main__":
    main()
