"""Fetch JPL Horizons apparent positions and store them as a test fixture.

docs/gates-spec.md g3 layer 1 requires the Seismograph ephemeris to agree with
an independent authority to 1 arc-minute. JPL Horizons is that authority. This
script asks it for QUANTITIES=31 — ObsEcLon/ObsEcLat, the *apparent* geocentric
ecliptic longitude and latitude referred to the true ecliptic and equinox of
date — which is exactly the frame a sidereal chart is built from once the
ayanamsa is subtracted.

Run it to regenerate tests/fixtures/horizons_anchors.json. The tests themselves
never touch the network; they read the stored fixture.
"""

from __future__ import annotations

import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path

API = "https://ssd.jpl.nasa.gov/api/horizons.api"

# Horizons body ids. Barycentres are wrong for the inner planets but right for
# the outer ones at arc-minute scale; we use the planet centres throughout so
# the comparison is apples to apples with Skyfield's planet targets.
BODIES = {
    "sun": "10",
    "moon": "301",
    "mercury": "199",
    "venus": "299",
    "mars": "499",
    "jupiter": "599",
    "saturn": "699",
}

# One instant per golden case family, spread across the DE421 span and both
# hemispheres' epochs. UTC, since Horizons START_TIME is UTC by default.
EPOCHS = [
    "1955-11-14 15:30",
    "1968-07-04 00:12",
    "1977-03-21 06:45",
    "1984-12-31 23:47",
    "1991-08-08 11:11",
    "2001-02-19 17:05",
    "2009-06-30 02:30",
    "2016-10-02 09:58",
]


def _fetch(body_id: str, epoch: str) -> tuple[float, float]:
    """Return (apparent ecliptic longitude, latitude) in degrees for one body."""
    # STOP_TIME must be strictly after START_TIME, so ask for a one minute span
    # and take the first row.
    start = epoch
    stop = _plus_one_minute(epoch)
    params = {
        "format": "text",
        "COMMAND": f"'{body_id}'",
        "OBJ_DATA": "'NO'",
        "MAKE_EPHEM": "'YES'",
        "EPHEM_TYPE": "'OBSERVER'",
        "CENTER": "'500@399'",  # geocentric
        "START_TIME": f"'{start}'",
        "STOP_TIME": f"'{stop}'",
        "STEP_SIZE": "'1m'",
        "QUANTITIES": "'31'",  # ObsEcLon, ObsEcLat (apparent, of date)
        "ANG_FORMAT": "'DEG'",
    }
    url = f"{API}?{urllib.parse.urlencode(params)}"
    with urllib.request.urlopen(url, timeout=60) as resp:  # noqa: S310 - fixed host
        text = resp.read().decode("utf-8", "replace")
    return _parse(text)


def _plus_one_minute(epoch: str) -> str:
    from datetime import datetime, timedelta

    dt = datetime.strptime(epoch, "%Y-%m-%d %H:%M") + timedelta(minutes=1)
    return dt.strftime("%Y-%m-%d %H:%M")


def _parse(text: str) -> tuple[float, float]:
    """Pull the first data row out of the $$SOE/$$EOE block."""
    if "$$SOE" not in text or "$$EOE" not in text:
        raise RuntimeError(f"Horizons returned no ephemeris block:\n{text[:800]}")
    block = text.split("$$SOE", 1)[1].split("$$EOE", 1)[0].strip()
    row = block.splitlines()[0]
    # "2001-Feb-19 17:05     331.123456  -0.000123"
    fields = row.split()
    lon, lat = float(fields[-2]), float(fields[-1])
    return lon, lat


def main() -> int:
    out: dict[str, dict[str, dict[str, float]]] = {}
    for epoch in EPOCHS:
        out[epoch] = {}
        for name, body_id in BODIES.items():
            lon, lat = _fetch(body_id, epoch)
            out[epoch][name] = {"lon_deg": lon, "lat_deg": lat}
            print(f"{epoch}  {name:<8} lon={lon:11.6f}  lat={lat:9.6f}", flush=True)

    path = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "horizons_anchors.json"
    payload = {
        "source": "JPL Horizons API, EPHEM_TYPE=OBSERVER, CENTER=500@399, QUANTITIES=31",
        "frame": "apparent geocentric ecliptic longitude/latitude of date (ObsEcLon/ObsEcLat)",
        "units": "degrees",
        "epochs_utc": EPOCHS,
        "bodies": BODIES,
        "positions": out,
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"\nwrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
