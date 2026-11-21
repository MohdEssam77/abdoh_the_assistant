"""Check that Abdoh can turn your monitors on and off. CHANGES YOUR SCREENS for a few seconds.

Lists the monitors with Abdoh's numbers, then keeps only one of them on for 8 seconds, and
puts the screens back exactly as they were, whatever happens. If anything goes wrong, Win+P
also brings screens back.

Usage: python scripts/display_check.py [number to keep on, default: the primary monitor]
"""

import sys
import time
from pathlib import Path

from abdoh.config import load_config
from abdoh.displays import Displays

SECONDS = 8


def main() -> int:
    cfg = load_config()
    displays = Displays(Path(cfg.app_dir) / "displays.json")
    found = displays.all()
    for d in found:
        print(f"  {d.number}: {d.label}  ({'on' if d.active else 'off'})")
    if len(found) < 2:
        print("Only one monitor is connected: nothing to switch.")
        return 1
    before = {d.id for d in found if d.active}
    keep = sys.argv[1] if len(sys.argv) > 1 else str(next(d.number for d in found if d.primary))
    try:
        started = time.perf_counter()
        print(f"Keeping only screen {keep} on for {SECONDS} seconds...")
        print("  ->", displays.apply(f"only {keep}"), f"({time.perf_counter() - started:.1f} s)")
        time.sleep(SECONDS)
    finally:
        started = time.perf_counter()
        after = displays.set_active(before)
        back = {d.id for d in after if d.active} == before
        print(f"Screens back as they were: {back} ({time.perf_counter() - started:.1f} s)")
    return 0 if back else 1


if __name__ == "__main__":
    sys.exit(main())
