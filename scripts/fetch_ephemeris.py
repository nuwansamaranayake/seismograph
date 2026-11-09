"""Download the JPL DE kernel that app/ephemeris.py reads.

The kernel is a 17 MB binary, so it is gitignored and fetched on demand rather
than committed. Run this once per machine (and once in CI) before the ephemeris
reference tests; app.ephemeris.load_ephemeris() calls the same loader.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.ephemeris import EPHEMERIS_DIR, KERNEL, load_ephemeris  # noqa: E402


def main() -> int:
    print(f"kernel   : {KERNEL}")
    print(f"directory: {EPHEMERIS_DIR}")
    eph = load_ephemeris()
    print(f"loaded   : {sorted(eph.names().values(), key=str)[:3]} ...")
    return 0


if __name__ == "__main__":
    sys.exit(main())
