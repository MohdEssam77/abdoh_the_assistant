"""Stop Xanthos from starting at login.

Usage: python scripts/uninstall_autostart.py
"""

import sys

from abdoh.autostart import uninstall

if __name__ == "__main__":
    try:
        print(uninstall())
    except Exception as e:
        print(f"Could not uninstall autostart: {e}")
        sys.exit(1)
