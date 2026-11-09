"""Generate suites/kalika/cases from the validated ephemeris reference.

docs/gates-spec.md g3 wants at least 12 birth records covering both
hemispheres, near-midnight births, near sign boundaries and near nakshatra
boundaries, and it wants them synthetic or published — never customer data.
Every record here is synthetic.

The reference block is *computed*, never typed. Golden values entered by hand
are how a suite ends up asserting a chart nobody ever checked: the four cases
this script replaced claimed a Magha Moon for an instant whose Moon is in
Uttara Ashadha. tests/test_ephemeris_reference.py is what makes the computed
values trustworthy — it pins app/ephemeris.py to JPL Horizons within one
arc-minute.

Boundary cases are found by search, not by guess: the script scans a day for an
instant whose margin to the boundary falls in a band close enough to be a real
boundary test but wide enough that an ayanamsa convention difference of a few
arc-minutes cannot flip the answer. The margin is recorded in the case so a
future reader can see how hard the case actually is.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.ephemeris import chart_facts  # noqa: E402

AS_OF = datetime(2026, 9, 19, tzinfo=UTC)
"""Mahadasha is a function of the clock, so the suite pins the instant it asks about."""

CASES_DIR = Path(__file__).resolve().parents[1] / "suites" / "kalika" / "cases"

# Margin band for boundary searches, degrees. The floor keeps a case from
# turning on an arc-minute of ayanamsa convention; the ceiling keeps it a
# boundary case rather than an ordinary one.
MARGIN_MIN_DEG = 0.08
MARGIN_MAX_DEG = 0.60


@dataclass(frozen=True)
class Place:
    name: str
    tz: str
    lat: float
    lon: float


LONDON = Place("London, UK", "Europe/London", 51.5072, -0.1276)
SYDNEY = Place("Sydney, Australia", "Australia/Sydney", -33.8688, 151.2093)
REYKJAVIK = Place("Reykjavik, Iceland", "Atlantic/Reykjavik", 64.1466, -21.9426)
NAIROBI = Place("Nairobi, Kenya", "Africa/Nairobi", -1.2921, 36.8219)
BUENOS_AIRES = Place("Buenos Aires, Argentina", "America/Argentina/Buenos_Aires", -34.6037, -58.3816)
TORONTO = Place("Toronto, Canada", "America/Toronto", 43.6532, -79.3832)
CAPE_TOWN = Place("Cape Town, South Africa", "Africa/Johannesburg", -33.9249, 18.4241)
COLOMBO = Place("Colombo, Sri Lanka", "Asia/Colombo", 6.9271, 79.8612)
SANTIAGO = Place("Santiago, Chile", "America/Santiago", -33.4489, -70.6693)
ANCHORAGE = Place("Anchorage, USA", "America/Anchorage", 61.2181, -149.9003)
WELLINGTON = Place("Wellington, New Zealand", "Pacific/Auckland", -41.2866, 174.7756)
QUITO = Place("Quito, Ecuador", "America/Guayaquil", -0.1807, -78.4678)
MUMBAI = Place("Mumbai, India", "Asia/Kolkata", 19.0760, 72.8777)


def _birth(place: Place, date: str, time: str) -> datetime:
    return datetime.strptime(f"{date} {time}", "%Y-%m-%d %H:%M").replace(
        tzinfo=ZoneInfo(place.tz)
    )


def _facts(place: Place, when: datetime):
    return chart_facts(when, place.lat, place.lon, AS_OF)


def _margin_to_boundary(lon: float, span: float) -> float:
    """Degrees from `lon` to the nearest multiple of `span`."""
    within = lon % span
    return min(within, span - within)


def _lagna_margin(facts) -> float:
    return _margin_to_boundary(facts.lagna_lon_deg, 30.0)


def _nakshatra_margin(facts) -> float:
    return _margin_to_boundary(facts.graha_lon_deg["moon"], 360.0 / 27.0)


def _pada_margin(facts) -> float:
    return _margin_to_boundary(facts.graha_lon_deg["moon"], 360.0 / 108.0)


def _sun_sign_margin(facts) -> float:
    return _margin_to_boundary(facts.graha_lon_deg["sun"], 30.0)


def _search(place: Place, date: str, metric, days: int = 3):
    """Find the minute nearest a boundary whose margin still lands in the band.

    Coarse pass every 15 minutes to locate the closest approach — the ascendant
    moves ~0.25 deg/minute and the Moon ~0.009 deg/minute, so no single step
    size suits both — then a minute-by-minute pass around it. Raises if nothing
    in the window qualifies: a loud failure beats a case that quietly is not a
    boundary case.
    """
    origin = _birth(place, date, "00:00")
    target = (MARGIN_MIN_DEG + MARGIN_MAX_DEG) / 2.0

    def at(minute: int):
        when = origin + timedelta(minutes=minute)
        facts = _facts(place, when)
        return when, facts, metric(facts)

    # Coarse pass to locate the closest approach to a boundary.
    crossing = min(
        (at(minute) for minute in range(0, days * 24 * 60, 15)),
        key=lambda triple: triple[2],
    )
    crossing_minute = round((crossing[0] - origin).total_seconds() / 60.0)

    # Step away from the crossing by however long this body needs to open up
    # the target margin. The ascendant covers it in a minute or two; the Sun
    # takes most of a day, so a fixed neighbourhood cannot serve both.
    rate = abs(at(crossing_minute + 15)[2] - crossing[2]) / 15.0
    if rate <= 0:
        raise RuntimeError(f"{place.name} {date}: metric does not move with time")
    offset = int(round(target / rate))

    best = None
    for centre in (crossing_minute + offset, crossing_minute - offset):
        for minute in range(centre - 10, centre + 11):
            if minute < 0:
                continue
            when, facts, margin = at(minute)
            if MARGIN_MIN_DEG <= margin <= MARGIN_MAX_DEG:
                return when, facts, margin
            if best is None or abs(margin - target) < abs(best[2] - target):
                best = (when, facts, margin)
    raise RuntimeError(
        f"no instant within {days} days of {date} at {place.name} lands in the "
        f"margin band (closest was {best[2]:.4f} deg)"
    )


def _case(case_id: str, note: str, place: Place, when: datetime, facts, tool: str,
          margin: dict[str, float] | None = None) -> dict:
    local = when.astimezone(ZoneInfo(place.tz))
    case = {
        "id": case_id,
        "source": "synthetic (no customer data; docs/gates-spec.md g3)",
        "note": note,
        "request": {
            "case_id": case_id,
            "tool": tool,
            "birth": {
                "date": local.strftime("%Y-%m-%d"),
                "time": local.strftime("%H:%M"),
                "tz": place.tz,
                "lat": place.lat,
                "lon": place.lon,
                "place": place.name,
            },
        },
        "as_of": AS_OF.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "reference": {
            "lagna": facts.lagna,
            "moon_nakshatra": facts.moon_nakshatra,
            "moon_pada": facts.moon_pada,
            "mahadasha_lord": facts.mahadasha_lord,
            "mahadasha_years_remaining": round(facts.mahadasha_years_remaining, 2),
            "ayanamsa_deg": round(facts.ayanamsa_deg, 6),
            "lagna_lon_deg": round(facts.lagna_lon_deg, 4),
            "graha_lon_deg": {k: round(v, 4) for k, v in facts.graha_lon_deg.items()},
            "graha_sign": dict(facts.graha_sign),
        },
        "provenance": {
            "computed_by": "app/ephemeris.py (Skyfield + JPL DE421)",
            "validated_by": "tests/test_ephemeris_reference.py (JPL Horizons, < 1 arc-minute)",
            "ayanamsa": "Lahiri fallback; live runs compare on the calculator's reported ayanamsa",
        },
    }
    if margin:
        case["provenance"]["boundary_margin_deg"] = {
            k: round(v, 4) for k, v in margin.items()
        }
    return case


def build() -> list[dict]:
    cases: list[dict] = []

    # --- plain cases, both hemispheres, a spread of decades -----------------
    plain = [
        ("syn-north-midday", LONDON, "1955-11-14", "15:30",
         "Northern hemisphere, mid-afternoon, nothing near a boundary: the case that should be easy.",
         "full_life_reading"),
        ("syn-south-midnight", SYDNEY, "1984-12-31", "23:47",
         "Southern hemisphere, thirteen minutes before midnight, so a date-handling slip moves the lagna a whole sign.",
         "full_life_reading"),
        ("syn-north-highlat", REYKJAVIK, "1968-07-04", "00:12",
         "Latitude 64 N just after midnight: ascendant signs pass at wildly uneven rates this far north.",
         "analyze_career"),
        ("syn-equator-dawn", NAIROBI, "1977-03-21", "06:45",
         "On the equator at equinox dawn, where ascendant motion is at its most uniform.",
         "analyze_career"),
        ("syn-south-evening", SANTIAGO, "1991-08-08", "19:22",
         "Southern hemisphere evening birth, mid-span of the kernel.",
         "analyze_marriage"),
        ("syn-north-subarctic", ANCHORAGE, "2009-06-30", "02:30",
         "Sub-arctic summer night: the sun is barely below the horizon and the ascendant is moving fast.",
         "ask_astrology_question"),
        ("syn-south-antipodal-midnight", WELLINGTON, "2016-10-02", "00:03",
         "Three minutes past midnight at UTC+13, the largest offset the suite covers.",
         "full_life_reading"),
        ("syn-equator-southern", QUITO, "1999-05-17", "12:00",
         "Noon on the equator in the southern hemisphere, UTC-5.",
         "analyze_marriage"),
    ]
    for case_id, place, date, time, note, tool in plain:
        when = _birth(place, date, time)
        cases.append(_case(case_id, note, place, when, _facts(place, when), tool))

    # --- boundary cases, found by search ------------------------------------
    when, facts, margin = _search(SYDNEY, "2001-02-19", _nakshatra_margin)
    cases.append(_case(
        "syn-nakshatra-boundary",
        f"Moon {margin:.2f} deg from a nakshatra boundary ({facts.moon_nakshatra}), "
        "so nakshatra and pada are the sensitive facts here.",
        SYDNEY, when, facts, "full_life_reading",
        {"moon_to_nakshatra_boundary": margin},
    ))

    when, facts, margin = _search(LONDON, "1963-04-11", _lagna_margin)
    cases.append(_case(
        "syn-sign-boundary",
        f"Lagna {margin:.2f} deg from a sign boundary ({facts.lagna}); a few minutes of "
        "birth-time error changes the rising sign.",
        LONDON, when, facts, "full_life_reading",
        {"lagna_to_sign_boundary": margin},
    ))

    when, facts, margin = _search(BUENOS_AIRES, "1988-09-23", _pada_margin)
    cases.append(_case(
        "syn-pada-boundary",
        f"Moon {margin:.2f} deg from a pada boundary (pada {facts.moon_pada} of "
        f"{facts.moon_nakshatra}), which also fixes the Vimshottari balance.",
        BUENOS_AIRES, when, facts, "full_life_reading",
        {"moon_to_pada_boundary": margin},
    ))

    when, facts, margin = _search(CAPE_TOWN, "1972-06-15", _lagna_margin)
    cases.append(_case(
        "syn-south-sign-boundary",
        f"Southern hemisphere lagna {margin:.2f} deg from a sign boundary ({facts.lagna}).",
        CAPE_TOWN, when, facts, "analyze_career",
        {"lagna_to_sign_boundary": margin},
    ))

    when, facts, margin = _search(COLOMBO, "1995-01-14", _sun_sign_margin)
    cases.append(_case(
        "syn-sun-sign-boundary",
        f"Sun {margin:.2f} deg from a sidereal sign boundary ({facts.graha_sign['sun']}) "
        "around Makara Sankranti, where tropical and sidereal engines disagree loudest.",
        COLOMBO, when, facts, "full_life_reading",
        {"sun_to_sign_boundary": margin},
    ))

    when, facts, margin = _search(MUMBAI, "2003-11-08", _nakshatra_margin)
    cases.append(_case(
        "syn-nakshatra-boundary-north",
        f"Northern hemisphere Moon {margin:.2f} deg from a nakshatra boundary "
        f"({facts.moon_nakshatra}).",
        MUMBAI, when, facts, "ask_astrology_question",
        {"moon_to_nakshatra_boundary": margin},
    ))

    when = _birth(TORONTO, "1980-02-29", "23:58")
    cases.append(_case(
        "syn-leap-day-midnight",
        "Two minutes before midnight on a leap day: date arithmetic and near-midnight "
        "handling fail together here or not at all.",
        TORONTO, when, _facts(TORONTO, when), "full_life_reading",
    ))

    return cases


def main() -> int:
    cases = build()
    ids = [c["id"] for c in cases]
    if len(set(ids)) != len(ids):
        raise RuntimeError(f"duplicate case ids: {ids}")
    if len(cases) < 12:
        raise RuntimeError(f"g3 requires at least 12 cases, built {len(cases)}")

    for stale in CASES_DIR.glob("*.json"):
        if stale.stem not in set(ids):
            stale.unlink()
    for case in cases:
        path = CASES_DIR / f"{case['id']}.json"
        path.write_text(json.dumps(case, indent=2) + "\n", encoding="utf-8")
        ref = case["reference"]
        print(
            f"{case['id']:<32} {ref['lagna']:<10} {ref['moon_nakshatra']:<18} "
            f"pada {ref['moon_pada']}  {ref['mahadasha_lord']}"
        )
    print(f"\nwrote {len(cases)} cases to {CASES_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
