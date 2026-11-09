"""The suite loader, the runner's three failure kinds, and the alert path.

These cover what the g4 gate cannot: the gate proves the CLI's exit code against
two live fixture containers, but it cannot cheaply prove that drift is detected,
that a stale baseline is refused, or that a layer with no judge is reported as
incomplete rather than passed. Those are the ways a green eval lies.
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from app.alerts import RECIPIENT, AlertError, send_alert
from app.runner import header_for, load_baseline, run_suite, write_baseline
from app.suite import SuiteError, load_suite
from app.targets import CallRecord

SUITE_ROOT = Path(__file__).resolve().parent.parent / "suites" / "kalika"

CHART_FIELDS = ("lagna", "moon_nakshatra", "moon_pada", "mahadasha_lord",
                "mahadasha_years_remaining")


def _reference_chart(case_id: str) -> dict:
    """The golden reference is computed (scripts/build_kalika_cases.py), so the test
    double reads it from the case file instead of repeating values that go stale."""
    case = json.loads((SUITE_ROOT / "cases" / f"{case_id}.json").read_text(encoding="utf-8"))
    return {field: case["reference"][field] for field in CHART_FIELDS}


def _clean_prose(chart: dict) -> str:
    return (
        f"Your lagna is {chart['lagna']} and the Moon sits in {chart['moon_nakshatra']} "
        f"pada {chart['moon_pada']}. You are running the {chart['mahadasha_lord']} "
        "mahadasha. You can meet this period with steady discipline."
    )


class FakeTarget:
    """Answers from the golden reference, optionally with a planted defect."""

    def __init__(self, target_id: str = "fake", *, tamper: str | None = None,
                 flaky: bool = False):
        self.target_id = target_id
        self.tamper = tamper
        self.flaky = flaky
        self.calls = 0

    def call(self, body: dict, json_path: str | None = None) -> CallRecord:
        self.calls += 1
        if self.tamper == "error":
            return CallRecord(self.target_id, "http", "POST /", "h", 1, error="ConnectError: down")
        chart = _reference_chart(body["case_id"])
        prose = _clean_prose(chart)
        payload = {"case_id": body["case_id"], "chart": chart, "prose": prose}
        if self.tamper == "lagna":
            chart["lagna"] = "Simha" if chart["lagna"] != "Simha" else "Kanya"
        if self.tamper == "gemstone":
            payload["prose"] = prose + " You should wear a blue sapphire gemstone."
        if self.flaky:
            chart["mahadasha_years_remaining"] += self.calls / 100
        return CallRecord(self.target_id, "http", "POST /", "h", 1, raw_response=payload)


def _suite():
    return load_suite(SUITE_ROOT)


def _one_case_suite():
    """The shipped suite narrowed to the case FakeTarget answers for."""
    suite = _suite()
    case = next(c for c in suite.cases if c.id == "syn-north-midday")
    return type(suite)(**{**suite.__dict__, "cases": (case,)})


# --------------------------------------------------------------------------- #
# loading and selection
# --------------------------------------------------------------------------- #
def test_shipped_suite_loads_with_layers_and_profiles():
    suite = _suite()
    assert suite.name == "kalika" and suite.version == "v1"
    assert [layer.name for layer in suite.layers] == ["engine", "policy"]
    assert set(suite.profiles) == {"daily", "full"}
    assert len(suite.cases) >= 4
    assert all(c.source.startswith("synthetic") for c in suite.cases), "no customer data in suites/"


def test_missing_suite_raises_rather_than_running_nothing(tmp_path):
    with pytest.raises(SuiteError):
        load_suite(tmp_path / "nope")


def test_daily_rotation_is_stable_within_a_day_and_moves_between_days():
    suite = _suite()
    daily = suite.profile("daily")
    day = date(2026, 9, 19)
    assert suite.select(daily, day) == suite.select(daily, day)
    assert len(suite.select(daily, day)) == daily.rotate
    seen = {c.id for d in range(7) for c in suite.select(daily, date.fromordinal(day.toordinal() + d))}
    assert seen == {c.id for c in suite.cases}, "a rotating profile must still cover every case"


def test_full_profile_selects_every_case():
    suite = _suite()
    assert suite.select(suite.profile("full"), date(2026, 9, 19)) == suite.cases


# --------------------------------------------------------------------------- #
# the three failure kinds
# --------------------------------------------------------------------------- #
def test_clean_target_passes_every_layer():
    suite = _one_case_suite()
    result = run_suite(suite, FakeTarget(), suite.profile("daily"), on=date(2026, 9, 19))
    assert [o.layer for o in result.outcomes] == ["engine", "policy"]
    assert result.failures == [] and result.incomplete == []


@pytest.mark.parametrize(
    "tamper,layer,marker",
    [("lagna", "engine", "chart.lagna"), ("gemstone", "policy", "forbidden[gemstone]")],
)
def test_planted_defect_fails_the_layer_that_owns_it(tamper, layer, marker):
    suite = _one_case_suite()
    result = run_suite(suite, FakeTarget(tamper=tamper), suite.profile("daily"),
                       on=date(2026, 9, 19))
    failed = {o.layer: o for o in result.failures}
    assert layer in failed
    assert any(marker in reason for reason in failed[layer].reasons)


def test_a_failed_call_is_a_failed_run_not_an_empty_pass():
    suite = _one_case_suite()
    result = run_suite(suite, FakeTarget(tamper="error"), suite.profile("daily"),
                       on=date(2026, 9, 19))
    assert [o.layer for o in result.failures] == ["target"]


def test_repeats_that_disagree_fail_determinism():
    suite = _one_case_suite()
    result = run_suite(suite, FakeTarget(flaky=True), suite.profile("full"), on=date(2026, 9, 19))
    assert any(o.layer == "determinism" and not o.passed for o in result.outcomes)


def test_a_judge_layer_without_a_judge_is_incomplete_never_passed():
    suite = _one_case_suite()
    grounded = type(suite.layers[0])(name="grounding", check="grounded", policy={})
    suite = type(suite)(**{**suite.__dict__, "layers": (grounded,)})
    result = run_suite(suite, FakeTarget(), suite.profile("daily"), on=date(2026, 9, 19))
    assert result.outcomes == []
    assert result.incomplete and "SEISMO_JUDGE_MODEL is unset" in result.incomplete[0]


# --------------------------------------------------------------------------- #
# baseline and drift
# --------------------------------------------------------------------------- #
def test_drift_is_a_layer_that_passed_in_the_baseline_and_fails_now(tmp_path):
    suite = _one_case_suite()
    profile = suite.profile("daily")
    clean = run_suite(suite, FakeTarget(), profile, on=date(2026, 9, 19))
    path = tmp_path / "fake.json"
    write_baseline(path, clean)

    header = header_for(suite, profile, "fake", None, False)
    baseline = load_baseline(path, header)
    after = run_suite(suite, FakeTarget(tamper="lagna"), profile, on=date(2026, 9, 19),
                      baseline=baseline)
    assert after.drifted == ["syn-north-midday::engine"]
    assert after.unbaselined == []


def test_a_baseline_from_a_different_header_is_refused(tmp_path):
    suite = _one_case_suite()
    profile = suite.profile("daily")
    write_baseline(tmp_path / "fake.json", run_suite(suite, FakeTarget(), profile,
                                                     on=date(2026, 9, 19)))
    other = header_for(suite, profile, "fake", "some/judge-model", False)
    with pytest.raises(RuntimeError, match="header mismatch"):
        load_baseline(tmp_path / "fake.json", other)


def test_the_shipped_fixture_baseline_matches_the_shipped_suite():
    """The committed baseline is the one the gate reads. If a suite edit lands
    without re-running scripts/g4_baseline.py, catch it here, not in the gate."""
    suite = _suite()
    stored = json.loads((SUITE_ROOT / "baseline" / "kalika-stub.json").read_text(encoding="utf-8"))
    assert stored["header"]["suite_sha256_16"] == suite.content_sha256_16()


def test_the_suite_digest_does_not_depend_on_checkout_line_endings(tmp_path):
    import shutil

    lf, crlf = tmp_path / "lf", tmp_path / "crlf"
    for root, newline in ((lf, b"\n"), (crlf, b"\r\n")):
        shutil.copytree(SUITE_ROOT, root)
        for path in root.rglob("*"):
            if path.is_file():
                text = path.read_bytes().replace(b"\r\n", b"\n")
                path.write_bytes(text.replace(b"\n", newline))
    assert load_suite(lf).content_sha256_16() == load_suite(crlf).content_sha256_16()


# --------------------------------------------------------------------------- #
# alerting
# --------------------------------------------------------------------------- #
def test_alert_without_a_key_raises_rather_than_silently_not_alerting(monkeypatch):
    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    with pytest.raises(AlertError, match="RESEND_API_KEY"):
        send_alert("subject", "body")


def test_the_only_alert_recipient_is_the_authorized_one():
    assert RECIPIENT == "nuwan@aigniteconsulting.ai"
