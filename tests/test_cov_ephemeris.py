"""Cover the remaining ephemeris error paths: loader failure, pole guard, as_of before birth."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app import ephemeris

T0 = datetime(1990, 6, 15, 12, 0, tzinfo=UTC)


def test_load_failure_raises_ephemeris_unavailable(monkeypatch, tmp_path):
    class BadLoader:
        def __init__(self, *a, **k):
            pass

        def __call__(self, name):
            raise OSError("disk full")

    ephemeris.load_ephemeris.cache_clear()
    monkeypatch.setattr(ephemeris, "EPHEMERIS_DIR", tmp_path / "eph")
    monkeypatch.setattr(ephemeris, "Loader", BadLoader)
    try:
        with pytest.raises(ephemeris.EphemerisUnavailable, match="disk full") as ei:
            ephemeris.load_ephemeris()
        assert "fetch_ephemeris.py" in str(ei.value)
        assert (tmp_path / "eph").is_dir()
    finally:
        ephemeris.load_ephemeris.cache_clear()


@pytest.mark.parametrize("lat", [89.0, -89.5, 90.0])
def test_ascendant_rejects_polar_latitude(lat):
    with pytest.raises(ValueError, match="poles"):
        ephemeris.ascendant_lon_deg(T0, lat, 0.0)


def test_mahadasha_rejects_as_of_before_birth():
    with pytest.raises(ValueError, match="as_of precedes birth"):
        ephemeris.mahadasha(10.0, T0, T0 - timedelta(days=1))
