"""Start Xanthos automatically at login (window hidden).

Usage: python scripts/install_autostart.py   (run with the Python where abdoh is installed)
"""

import sys

from abdoh.autostart import install

if __name__ == "__main__":
    try:
        print(install())
    except Exception as e:
        print(f"Could not install autostart: {e}")
        sys.exit(1)
