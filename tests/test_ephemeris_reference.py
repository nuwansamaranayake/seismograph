"""Prove app/ephemeris.py is accurate enough to be the g3 layer-1 reference.

docs/gates-spec.md g3 layer 1 puts a 1 arc-minute tolerance on longitudes. A
reference that has not been measured against an outside authority is not a
reference, it is a second guess — so the first test here compares against JPL
Horizons apparent positions captured by scripts/fetch_horizons_anchors.py, and
the second proves the comparison is actually sensitive to the frame mistake
that is easy to make (J2000 instead of equinox of date).

The tests read a stored fixture and never touch the network. They do need the
DE kernel on disk: `python scripts/fetch_ephemeris.py`.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.ephemeris import (
    GRAHAS,
    NAKSHATRAS,
    VIMSHOTTARI,
    VIMSHOTTARI_TOTAL_YEARS,
    EphemerisUnavailable,
    apparent_positions,
    ascendant_lon_deg,
    chart_facts,
    load_ephemeris,
    mahadasha,
    nakshatra_pada,
    sign_of,
)

ARCMINUTE_DEG = 1.0 / 60.0
REPO = Path(__file__).resolve().parents[1]
ANCHORS = json.loads(
    (REPO / "tests" / "fixtures" / "horizons_anchors.json").read_text(encoding="utf-8")
)


def _epoch(text: str) -> datetime:
    return datetime.strptime(text, "%Y-%m-%d %H:%M").replace(tzinfo=UTC)


def _anchor_cases() -> list[tuple[str, str, float, float]]:
    cases = []
    for epoch, bodies in ANCHORS["positions"].items():
        for body, pos in bodies.items():
            cases.append((epoch, body, pos["lon_deg"], pos["lat_deg"]))
    return sorted(cases)


def _separation_deg(a: float, b: float) -> float:
    """Smallest absolute angular difference, degrees."""
    return abs((a - b + 180.0) % 360.0 - 180.0)


@pytest.fixture(scope="session", autouse=True)
def _kernel_present():
    """Fail loudly, never skip: an unmeasured reference must not look green."""
    try:
        load_ephemeris()
    except EphemerisUnavailable as exc:
        pytest.fail(str(exc))


@pytest.mark.parametrize(("epoch", "body", "lon", "lat"), _anchor_cases())
def test_apparent_position_matches_horizons(epoch: str, body: str, lon: float, lat: float):
    """Every anchor agrees with JPL Horizons inside one arc-minute."""
    computed = apparent_positions(_epoch(epoch))[body]
    assert _separation_deg(computed.lon_deg, lon) < ARCMINUTE_DEG, (
        f"{body} @ {epoch}: longitude {computed.lon_deg:.6f} vs Horizons {lon:.6f}"
    )
    assert abs(computed.lat_deg - lat) < ARCMINUTE_DEG, (
        f"{body} @ {epoch}: latitude {computed.lat_deg:.6f} vs Horizons {lat:.6f}"
    )


def test_anchor_set_covers_every_visible_graha_across_the_span():
    """Guard the fixture itself: a thinned anchor set would weaken the test above."""
    epochs = set(ANCHORS["positions"])
    assert len(epochs) >= 8
    years = {int(e[:4]) for e in epochs}
    assert max(years) - min(years) > 50, "anchors must span decades, not one epoch"
    for bodies in ANCHORS["positions"].values():
        assert set(bodies) == {
            "sun", "moon", "mercury", "venus", "mars", "jupiter", "saturn",
        }


def test_tolerance_detects_the_wrong_equinox():
    """The J2000 frame must fail the same check the of-date frame passes.

    Pass 7 measured ~5.5 arc-minutes of error and could not tell whether the
    library or the anchor was at fault. This is the discriminator: if a
    deliberately wrong frame still landed inside a mutated tolerance, a silent
    frame regression would never be caught.
    """
    from skyfield.api import Loader

    from app.ephemeris import _TARGETS, EPHEMERIS_DIR

    eph = load_ephemeris()
    ts = Loader(str(EPHEMERIS_DIR), verbose=False).timescale()
    epoch = "1955-11-14 15:30"
    t = ts.from_datetime(_epoch(epoch))

    worst = 0.0
    for body, target in _TARGETS.items():
        j2000 = eph["earth"].at(t).observe(eph[target]).apparent().ecliptic_latlon()
        worst = max(worst, _separation_deg(j2000[1].degrees, ANCHORS["positions"][epoch][body]["lon_deg"]))
    assert worst > 10 * ARCMINUTE_DEG, (
        "J2000 longitudes came out within 10 arc-minutes of the of-date anchors, "
        "so this test cannot tell the two frames apart"
    )


def test_ascendant_advances_through_all_twelve_signs_in_a_day():
    """A day's worth of ascendants must sweep the whole zodiac, monotonically."""
    base = datetime(1991, 8, 8, 0, 0, tzinfo=UTC)
    seen = {sign_of(ascendant_lon_deg(base + timedelta(minutes=10 * i), 6.9271, 79.8612))
            for i in range(144)}
    assert seen == set(sign_of(30.0 * i) for i in range(12))


def test_nakshatra_pada_partitions_the_zodiac():
    span = 360.0 / 27.0
    for index, name in enumerate(NAKSHATRAS):
        start = index * span
        assert nakshatra_pada(start + 1e-6) == (name, 1)
        assert nakshatra_pada(start + span * 0.9) == (name, 4)
    assert nakshatra_pada(359.999)[0] == "Revati"
    assert nakshatra_pada(0.0) == ("Ashwini", 1)


def test_vimshottari_periods_sum_to_one_cycle():
    assert sum(years for _, years in VIMSHOTTARI) == VIMSHOTTARI_TOTAL_YEARS


def test_mahadasha_balance_at_birth_matches_the_unelapsed_nakshatra():
    """Born at the exact start of Ashwini: the full 7-year Ketu period remains."""
    birth = datetime(1991, 8, 8, 11, 11, tzinfo=UTC)
    lord, remaining = mahadasha(0.0, birth, birth)
    assert lord == "Ketu"
    assert remaining == pytest.approx(7.0)

    # Halfway through Ashwini halves the balance, and the lord is unchanged.
    lord, remaining = mahadasha((360.0 / 27.0) / 2.0, birth, birth)
    assert lord == "Ketu"
    assert remaining == pytest.approx(3.5)


def test_mahadasha_walks_the_cycle_forward():
    """Past the birth period's end, the next lord in nakshatra order takes over."""
    birth = datetime(1991, 8, 8, 11, 11, tzinfo=UTC)
    seven_years = timedelta(days=7 * 365.25)
    lord, remaining = mahadasha(0.0, birth, birth + seven_years + timedelta(days=1))
    assert lord == "Venus"
    assert 19.9 < remaining <= 20.0


def test_mahadasha_returns_to_the_same_lord_after_a_full_cycle():
    birth = datetime(1968, 7, 4, 0, 12, tzinfo=UTC)
    at_birth = mahadasha(123.4, birth, birth)
    a_cycle_on = mahadasha(123.4, birth, birth + timedelta(days=120 * 365.25))
    assert a_cycle_on[0] == at_birth[0]
    assert a_cycle_on[1] == pytest.approx(at_birth[1], abs=1e-6)


def test_chart_facts_uses_the_ayanamsa_it_is_given():
    """Signs must move with the calculator's ayanamsa, not a value we prefer."""
    birth = datetime(2001, 2, 19, 17, 5, tzinfo=UTC)
    as_of = datetime(2026, 9, 19, tzinfo=UTC)
    low = chart_facts(birth, 51.5072, -0.1276, as_of, ayanamsa_deg=0.0)
    high = chart_facts(birth, 51.5072, -0.1276, as_of, ayanamsa_deg=24.0)
    assert low.ayanamsa_deg == 0.0
    for graha in GRAHAS:
        assert _separation_deg(low.graha_lon_deg[graha] - 24.0,
                               high.graha_lon_deg[graha]) < 1e-9


def test_rahu_and_ketu_stay_opposite():
    facts = chart_facts(
        datetime(1977, 3, 21, 6, 45, tzinfo=UTC),
        -33.8688, 151.2093,
        datetime(2026, 9, 19, tzinfo=UTC),
    )
    assert _separation_deg(facts.graha_lon_deg["rahu"] + 180.0,
                           facts.graha_lon_deg["ketu"]) < 1e-9


def _golden_cases() -> list[dict]:
    return [
        json.loads(p.read_text(encoding="utf-8"))
        for p in sorted((REPO / "suites" / "kalika" / "cases").glob("*.json"))
    ]


def test_golden_cases_meet_the_g3_coverage_requirement():
    """At least 12 records, both hemispheres, near-midnight, and both boundaries."""
    cases = _golden_cases()
    assert len(cases) >= 12

    latitudes = [c["request"]["birth"]["lat"] for c in cases]
    assert any(lat > 0 for lat in latitudes), "no northern hemisphere case"
    assert any(lat < 0 for lat in latitudes), "no southern hemisphere case"

    def minutes_from_midnight(case: dict) -> int:
        hour, minute = (int(x) for x in case["request"]["birth"]["time"].split(":"))
        clock = hour * 60 + minute
        return min(clock, 24 * 60 - clock)

    assert any(minutes_from_midnight(c) <= 15 for c in cases), "no near-midnight case"

    margins: set[str] = set()
    for case in cases:
        margins.update(case["provenance"].get("boundary_margin_deg", {}))
    assert "lagna_to_sign_boundary" in margins, "no near sign boundary case"
    assert "moon_to_nakshatra_boundary" in margins, "no near nakshatra boundary case"

    for case in cases:
        assert case["source"].startswith("synthetic"), (
            f"{case['id']}: g3 forbids customer data in the suite"
        )


@pytest.mark.parametrize("case", _golden_cases(), ids=lambda c: c["id"])
def test_golden_reference_reproduces_from_the_ephemeris(case: dict):
    """Every stored golden must fall out of app/ephemeris.py, not out of a keyboard.

    The four cases this suite started with asserted a Magha Moon for an instant
    whose Moon is in Uttara Ashadha. Regenerating is cheap; an unfalsifiable
    golden is not.
    """
    birth_spec = case["request"]["birth"]
    from zoneinfo import ZoneInfo

    birth = datetime.strptime(
        f"{birth_spec['date']} {birth_spec['time']}", "%Y-%m-%d %H:%M"
    ).replace(tzinfo=ZoneInfo(birth_spec["tz"]))
    as_of = datetime.strptime(case["as_of"], "%Y-%m-%dT%H:%M:%SZ").replace(
        tzinfo=UTC
    )

    facts = chart_facts(birth, birth_spec["lat"], birth_spec["lon"], as_of)
    reference = case["reference"]

    assert facts.lagna == reference["lagna"]
    assert facts.moon_nakshatra == reference["moon_nakshatra"]
    assert facts.moon_pada == reference["moon_pada"]
    assert facts.mahadasha_lord == reference["mahadasha_lord"]
    assert facts.mahadasha_years_remaining == pytest.approx(
        reference["mahadasha_years_remaining"], abs=0.01
    )
    for graha in GRAHAS:
        assert facts.graha_lon_deg[graha] == pytest.approx(
            reference["graha_lon_deg"][graha], abs=1e-4
        )


def test_naive_datetimes_are_refused():
    """A naive instant is an unanswerable question, not a UTC assumption."""
    with pytest.raises(ValueError):
        apparent_positions(datetime(2001, 2, 19, 17, 5))
