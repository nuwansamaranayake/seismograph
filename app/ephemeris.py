"""An independent ephemeris reference for the Kalika engine-correctness layer.

docs/gates-spec.md g3 layer 1 cross-checks the Kalika calculator's
`compute_chart` against an ephemeris computed *inside* Seismograph, so that a
calculator regression cannot silently redefine what "correct" means. This
module is that second opinion. It is deliberately not a chart engine: it
computes the handful of facts layer 1 asserts on and nothing else.

Library choice (DECISION D-7-3): Skyfield, MIT licensed, reading a JPL DE
kernel. The obvious alternative, pyswisseph, is AGPL-3.0, whose network clause
does not fit a hosted service.

Frames, stated once because getting this wrong is the usual way an ephemeris
reference silently drifts:

* Positions are **apparent geocentric ecliptic longitudes referred to the true
  ecliptic and equinox of date** — light-time corrected, aberration and
  deflection applied, precessed and nutated to the epoch of observation. That
  is the frame classical chart work assumes, and it is what JPL Horizons calls
  ObsEcLon/ObsEcLat (QUANTITIES=31). J2000 ecliptic longitudes differ from it
  by the accumulated precession, which for a birth in living memory is degrees,
  not arc-minutes. tests/test_ephemeris_reference.py pins this against stored
  Horizons output to the 1 arc-minute tolerance the gate requires.

* Sidereal longitudes are tropical minus the ayanamsa. The gate reads the
  ayanamsa out of the calculator's own output and passes it in, so signs,
  nakshatra and pada are compared on the calculator's own terms. The Lahiri
  value here is only the fallback used when building golden references.
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path

from skyfield.api import Loader
from skyfield.nutationlib import iau2000b

KERNEL = "de421.bsp"
"""JPL DE421. Spans 1899-07-29 to 2053-10-09 — every birth the suite covers.

Sub-arcsecond against DE440 over that span, i.e. two orders of magnitude inside
the gate's 1 arc-minute tolerance, at 17 MB instead of 114 MB.
"""

_DEFAULT_EPHEMERIS_DIR = Path(__file__).resolve().parents[1] / "data" / "ephemeris"
EPHEMERIS_DIR = Path(os.environ.get("SEISMO_EPHEMERIS_DIR", _DEFAULT_EPHEMERIS_DIR))
"""Where the kernel lives. Gitignored; `python scripts/fetch_ephemeris.py` fills it."""

# Skyfield target names for the seven visible grahas. Rahu and Ketu are not
# bodies and are computed from the lunar node below.
_TARGETS = {
    "sun": "sun",
    "moon": "moon",
    "mercury": "mercury",
    "venus": "venus",
    "mars": "mars",
    "jupiter": "jupiter barycenter",
    "saturn": "saturn barycenter",
}

GRAHAS = ("sun", "moon", "mars", "mercury", "jupiter", "venus", "saturn", "rahu", "ketu")

SIGNS = (
    "Mesha", "Vrishabha", "Mithuna", "Karka", "Simha", "Kanya",
    "Tula", "Vrischika", "Dhanu", "Makara", "Kumbha", "Meena",
)

NAKSHATRAS = (
    "Ashwini", "Bharani", "Krittika", "Rohini", "Mrigashira", "Ardra",
    "Punarvasu", "Pushya", "Ashlesha", "Magha", "Purva Phalguni", "Uttara Phalguni",
    "Hasta", "Chitra", "Swati", "Vishakha", "Anuradha", "Jyeshtha",
    "Mula", "Purva Ashadha", "Uttara Ashadha", "Shravana", "Dhanishta", "Shatabhisha",
    "Purva Bhadrapada", "Uttara Bhadrapada", "Revati",
)

# Vimshottari, in nakshatra order starting at Ashwini. 120 years per cycle.
VIMSHOTTARI = (
    ("Ketu", 7.0), ("Venus", 20.0), ("Sun", 6.0), ("Moon", 10.0), ("Mars", 7.0),
    ("Rahu", 18.0), ("Jupiter", 16.0), ("Saturn", 19.0), ("Mercury", 17.0),
)
VIMSHOTTARI_TOTAL_YEARS = 120.0
SIDEREAL_YEAR_DAYS = 365.25
"""Vimshottari years are conventionally Julian years of 365.25 days."""

_AYANAMSA_LAHIRI_J2000 = 23.853919
"""Lahiri (Chitrapaksha) ayanamsa at J2000.0, degrees.

Only a fallback for generating golden references. Live comparisons use the
ayanamsa the calculator itself reports, per docs/gates-spec.md g3 layer 1.
"""


class EphemerisUnavailable(RuntimeError):
    """The DE kernel is not on disk and could not be fetched.

    Raised loudly rather than silently falling back to a lower-fidelity model —
    a quiet fallback is exactly the failure mode the engine layer exists to
    catch (CLAUDE.md standard 3).
    """


@dataclass(frozen=True)
class Position:
    """One body's apparent ecliptic position, degrees, true equinox of date."""

    lon_deg: float
    lat_deg: float


@dataclass(frozen=True)
class ChartFacts:
    """The layer-1 assertion surface. Mirrors the `reference` block of a case."""

    ayanamsa_deg: float
    lagna: str
    lagna_lon_deg: float
    graha_lon_deg: dict[str, float]
    graha_sign: dict[str, str]
    moon_nakshatra: str
    moon_pada: int
    mahadasha_lord: str
    mahadasha_years_remaining: float


@lru_cache(maxsize=1)
def load_ephemeris():
    """Open the DE kernel, downloading it once if the directory is empty."""
    EPHEMERIS_DIR.mkdir(parents=True, exist_ok=True)
    loader = Loader(str(EPHEMERIS_DIR), verbose=False)
    try:
        return loader(KERNEL)
    except Exception as exc:  # network down, disk full, corrupt partial download
        raise EphemerisUnavailable(
            f"could not load {KERNEL} from {EPHEMERIS_DIR}: {exc}. "
            f"Run `python scripts/fetch_ephemeris.py`."
        ) from exc


@lru_cache(maxsize=1)
def _timescale():
    return Loader(str(EPHEMERIS_DIR), verbose=False).timescale()


def _time(when: datetime):
    if when.tzinfo is None:
        raise ValueError("birth instants must be timezone-aware")
    return _timescale().from_datetime(when.astimezone(UTC))


def apparent_positions(when: datetime) -> dict[str, Position]:
    """Apparent geocentric ecliptic positions of the seven visible grahas.

    True ecliptic and equinox of date. This is the function the Horizons
    validation test measures; everything else here is arithmetic on top of it.
    """
    eph = load_ephemeris()
    t = _time(when)
    earth = eph["earth"]
    out: dict[str, Position] = {}
    for name, target in _TARGETS.items():
        astrometric = earth.at(t).observe(eph[target])
        lat, lon, _ = astrometric.apparent().ecliptic_latlon(epoch=t)
        out[name] = Position(lon_deg=lon.degrees % 360.0, lat_deg=lat.degrees)
    return out


def mean_node_lon_deg(when: datetime) -> float:
    """Tropical longitude of the Moon's mean ascending node (Rahu), of date.

    Meeus, *Astronomical Algorithms* 2nd ed., eq. 47.7. The Indian ephemeris
    tradition Kalika follows uses the mean node, not the true node; the two
    differ by up to ~1.6 degrees, which is a convention difference and would
    show up as a finding, not as ephemeris error.
    """
    t = _time(when)
    T = (t.tt - 2451545.0) / 36525.0
    omega = (
        125.0445479
        - 1934.1362891 * T
        + 0.0020754 * T**2
        + T**3 / 467441.0
        - T**4 / 60616000.0
    )
    return omega % 360.0


def ayanamsa_lahiri_deg(when: datetime) -> float:
    """Lahiri ayanamsa, degrees: the J2000 value plus general precession since.

    Accumulated general precession in longitude is the IAU 2006 series
    (Capitaine et al. 2003), pA = 5028.796195"T + 1.1054348"T^2. Fallback only —
    see the module docstring.
    """
    t = _time(when)
    T = (t.tt - 2451545.0) / 36525.0
    precession_arcsec = 5028.796195 * T + 1.1054348 * T**2
    return _AYANAMSA_LAHIRI_J2000 + precession_arcsec / 3600.0


def true_obliquity_deg(when: datetime) -> float:
    """Obliquity of the ecliptic of date, degrees, including nutation."""
    t = _time(when)
    # Mean obliquity, IAU 1980 polynomial in arcseconds.
    T = (t.tt - 2451545.0) / 36525.0
    mean_arcsec = (
        84381.448
        - 46.8150 * T
        - 0.00059 * T**2
        + 0.001813 * T**3
    )
    _, deps_arcsec = iau2000b(t.tt)
    # iau2000b returns units of 0.1 microarcsecond.
    return (mean_arcsec + deps_arcsec / 1.0e7) / 3600.0


def ascendant_lon_deg(when: datetime, lat_deg: float, lon_deg: float) -> float:
    """Tropical ecliptic longitude of the ascendant, degrees.

    Standard spherical formula on the local apparent sidereal time; `lon_deg` is
    east-positive geographic longitude.
    """
    t = _time(when)
    # Guard against a latitude at the pole, where the ascendant is undefined.
    if abs(lat_deg) >= 89.0:
        raise ValueError("ascendant is undefined within one degree of the poles")
    ramc = math.radians((t.gast * 15.0 + lon_deg) % 360.0)
    eps = math.radians(true_obliquity_deg(when))
    phi = math.radians(lat_deg)
    asc = math.atan2(
        math.cos(ramc),
        -(math.sin(ramc) * math.cos(eps) + math.tan(phi) * math.sin(eps)),
    )
    return math.degrees(asc) % 360.0


def sign_of(sidereal_lon_deg: float) -> str:
    return SIGNS[int(sidereal_lon_deg % 360.0 // 30.0)]


def nakshatra_pada(moon_sidereal_lon_deg: float) -> tuple[str, int]:
    """Nakshatra name and pada (1-4) for a sidereal Moon longitude."""
    span = 360.0 / 27.0
    position = moon_sidereal_lon_deg % 360.0
    index = int(position // span)
    within = position - index * span
    pada = int(within // (span / 4.0)) + 1
    return NAKSHATRAS[index], pada


def mahadasha(
    moon_sidereal_lon_deg: float, birth: datetime, as_of: datetime
) -> tuple[str, float]:
    """Vimshottari mahadasha lord at `as_of`, and years left in it.

    The balance at birth is the unelapsed fraction of the Moon's nakshatra,
    scaled by that lord's period; the cycle then runs in nakshatra order.
    """
    span = 360.0 / 27.0
    position = moon_sidereal_lon_deg % 360.0
    index = int(position // span)
    elapsed_fraction = (position - index * span) / span

    order_index = index % 9
    lord, years = VIMSHOTTARI[order_index]
    remaining_at_birth = years * (1.0 - elapsed_fraction)

    age_years = (as_of - birth).total_seconds() / (86400.0 * SIDEREAL_YEAR_DAYS)
    if age_years < 0:
        raise ValueError("as_of precedes birth")

    if age_years < remaining_at_birth:
        return lord, remaining_at_birth - age_years

    # Walk the cycle forward from the end of the birth mahadasha.
    remainder = (age_years - remaining_at_birth) % VIMSHOTTARI_TOTAL_YEARS
    cursor = order_index
    while True:
        cursor = (cursor + 1) % 9
        lord, years = VIMSHOTTARI[cursor]
        if remainder < years:
            return lord, years - remainder
        remainder -= years


def chart_facts(
    birth: datetime,
    lat_deg: float,
    lon_deg: float,
    as_of: datetime,
    ayanamsa_deg: float | None = None,
) -> ChartFacts:
    """Every fact docs/gates-spec.md g3 layer 1 asserts on, in one call.

    `ayanamsa_deg` should be the value the calculator reported, so signs and
    nakshatra are compared on its own terms; passing None falls back to Lahiri.
    """
    ayanamsa = ayanamsa_lahiri_deg(birth) if ayanamsa_deg is None else ayanamsa_deg

    tropical = {name: pos.lon_deg for name, pos in apparent_positions(birth).items()}
    rahu = mean_node_lon_deg(birth)
    tropical["rahu"] = rahu
    tropical["ketu"] = (rahu + 180.0) % 360.0

    graha_lon = {name: (tropical[name] - ayanamsa) % 360.0 for name in GRAHAS}
    lagna_lon = (ascendant_lon_deg(birth, lat_deg, lon_deg) - ayanamsa) % 360.0
    nakshatra, pada = nakshatra_pada(graha_lon["moon"])
    lord, remaining = mahadasha(graha_lon["moon"], birth, as_of)

    return ChartFacts(
        ayanamsa_deg=ayanamsa,
        lagna=sign_of(lagna_lon),
        lagna_lon_deg=lagna_lon,
        graha_lon_deg=graha_lon,
        graha_sign={name: sign_of(graha_lon[name]) for name in GRAHAS},
        moon_nakshatra=nakshatra,
        moon_pada=pada,
        mahadasha_lord=lord,
        mahadasha_years_remaining=remaining,
    )
