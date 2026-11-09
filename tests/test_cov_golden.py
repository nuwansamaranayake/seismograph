"""app.engine.golden: statistics helpers, scenarios, the suite assembly and acceptance.

run_suite() refuses runs_per_cell < 30, so the full-suite tests replace the
expensive per-seed scenario with a scripted one and assert on structure and
invariants. The real run_scenario is exercised directly on a few seeds.
"""
from __future__ import annotations

import dataclasses
import math

import pytest

from app.engine import golden
from app.engine.golden import ScenarioResult
from app.engine.suts import DriftSUT, FlakySUT, JumpSUT, StableSUT


# ----------------------------------------------------------------- stats ---
def test_wilson_edges_and_midpoint():
    with pytest.raises(ValueError, match="zero trials"):
        golden.wilson(0, 0)
    p, lo, hi = golden.wilson(0, 30)
    assert p == 0.0 and lo == 0.0 and 0.0 < hi < 0.15
    p, lo, hi = golden.wilson(30, 30)
    assert p == 1.0 and hi == 1.0 and 0.85 < lo < 1.0
    p, lo, hi = golden.wilson(15, 30)
    assert p == 0.5 and lo < 0.5 < hi and (lo + hi) / 2 == pytest.approx(0.5, abs=0.01)


def test_sigma_and_flip_probability():
    expected = math.sqrt(0.04 * 0.96 / 40)
    assert golden.sigma_healthy() == pytest.approx(expected)
    assert golden.flip_p_for_sigma(0) == golden.HEALTHY_FLIP_P
    assert golden.flip_p_for_sigma(2) == pytest.approx(0.04 + 2 * expected)
    assert golden.flip_p_for_sigma(1000) == 1.0


def test_scenario_result_latency_ignores_pre_onset_alarms():
    r = ScenarioResult("c", 1, alarms=[3, golden.ONSET + 4, golden.ONSET + 9], points=40)
    assert r.latency() == 4 and r.detected()
    none = ScenarioResult("c", 1, alarms=[0, golden.ONSET - 1], points=40)
    assert none.latency() is None and not none.detected()
    assert not ScenarioResult("c", 1).detected()
    assert ScenarioResult("c", 1, alarms=[golden.ONSET]).latency() == 0


def test_entry_describes_the_repeat_run_cell():
    e = golden._entry()
    assert (e.probe_id, e.samples, e.configs) == ("golden", golden.N_SAMPLES, 1)
    assert e.invariant_fields == ["eligibility_decision"]


def test_embedder_identity_names_dimension():
    assert golden.embedder_identity() == "hashing/dim=256/v1"


# ----------------------------------------------------------- scenarios ---
def test_sut_for_each_kind_and_unknown():
    assert isinstance(golden._sut_for("null"), StableSUT)
    assert isinstance(golden._sut_for("shift:2.0"), JumpSUT)
    assert isinstance(golden._sut_for("drift:1.0"), DriftSUT)
    assert isinstance(golden._sut_for("flake:0.1"), FlakySUT)
    with pytest.raises(ValueError, match="unknown cell kind 'bogus'"):
        golden._sut_for("bogus:1")


def test_baseline_is_cached_and_has_expected_shape():
    flips, mals = golden._baseline(100)
    assert len(flips) == len(mals) == golden.BASELINE_W
    assert golden._baseline(100)[0] is flips
    assert all(0.0 <= f <= 1.0 for f in flips) and all(m == 0.0 for m in mals)


def test_metric_point_returns_rates_in_unit_interval():
    flip, mal = golden._metric_point(StableSUT(base_flip_p=golden.HEALTHY_FLIP_P), 0, 100)
    assert 0.0 <= flip <= 1.0 and mal == 0.0


def test_run_scenario_is_deterministic_and_counts_points():
    a = golden.run_scenario("null", 100)
    b = golden.run_scenario("null", 100)
    assert a.points == golden.RUN_T and a.cell == "null" and a.seed == 100
    assert a.alarms == b.alarms


def test_large_planted_shift_and_flake_are_detected_after_onset():
    shift = golden.run_scenario("shift:3.0", 100)
    assert shift.detected() and shift.latency() < 10
    assert all(0 <= t < golden.RUN_T for t in shift.alarms)
    flake = golden.run_scenario("flake:0.2", 100)
    assert flake.detected()


# ------------------------------------------------------------- summarize ---
def test_summarize_rejects_empty_and_vacuous():
    with pytest.raises(ValueError, match="zero runs"):
        golden.summarize("c", "l", [])
    with pytest.raises(ValueError, match="zero monitored points"):
        golden.summarize("c", "l", [ScenarioResult("c", 1, points=0)])


def test_summarize_counts_detections_and_median_latency():
    on = golden.ONSET
    results = [
        ScenarioResult("c", 1, alarms=[on + 2], points=40),
        ScenarioResult("c", 2, alarms=[on + 4, on + 5], points=40),
        ScenarioResult("c", 3, alarms=[1], points=40),        # pre-onset only: a miss
        ScenarioResult("c", 4, alarms=[], points=40),
    ]
    s = golden.summarize("c", "label", results)
    assert (s.runs, s.detections, s.sensitivity) == (4, 2, 0.5)
    assert s.latency_median == 3 and s.alarm_points == 4 and s.total_points == 160
    assert s.ci_low < 0.5 < s.ci_high
    miss = golden.summarize("c", "label", [ScenarioResult("c", 1, points=40)])
    assert miss.latency_median is None and miss.detections == 0


def test_svg_curve_contains_one_point_per_cell():
    cells = [golden.summarize(f"shift:{k}", "l",
                              [ScenarioResult("c", i, alarms=[golden.ONSET], points=40)
                               for i in range(30)]) for k in (0.5, 1.0, 2.0)]
    svg = golden._svg_curve(cells, 0.0123)
    assert svg.startswith("<svg") and svg.rstrip().endswith("</svg>")
    assert svg.count("<circle") == 3
    assert "false alarm rate 0.0123" in svg and "polyline" in svg


# --------------------------------------------------------------- run_suite ---
def _scripted(detect_from_shift, null_alarm_seeds=(), flake_detect=True, drift_detect=True):
    def fake(cell, seed):
        alarms = []
        kind, _, arg = cell.partition(":")
        if kind == "shift" and float(arg) >= detect_from_shift:
            alarms = [golden.ONSET + 1]
        elif kind == "drift" and drift_detect:
            alarms = [golden.ONSET + 3]
        elif kind == "flake" and flake_detect:
            alarms = [golden.ONSET + 2]
        elif kind == "null" and seed in null_alarm_seeds:
            alarms = [5]
        return ScenarioResult(cell, seed, alarms=alarms, points=golden.RUN_T)
    return fake


def test_run_suite_refuses_fewer_than_thirty_runs():
    with pytest.raises(ValueError, match="runs_per_cell < 30"):
        golden.run_suite(runs_per_cell=3)


def test_run_suite_assembles_report(monkeypatch):
    monkeypatch.setattr(golden, "run_scenario", _scripted(1.0, null_alarm_seeds=(100,)))
    r = golden.run_suite(30)
    assert [c.cell for c in r.shift] == [f"shift:{k}" for k in golden.SHIFT_SIGMAS]
    assert [c.cell for c in r.drift] == [f"drift:{k}" for k in golden.DRIFT_SIGMAS]
    assert [c.cell for c in r.flake] == [f"flake:{p}" for p in golden.FLAKE_RATES]
    assert r.null.cell == "null" and r.null.runs == 30
    assert r.false_alarm_rate == pytest.approx(1 / (30 * golden.RUN_T))
    assert r.far_ci[0] <= r.false_alarm_rate <= r.far_ci[1]
    assert r.detection_floor == 1.0          # first shift cell with ci_low >= 0.80
    assert [c.sensitivity for c in r.shift] == [0.0, 0.0, 1.0, 1.0, 1.0, 1.0]
    assert r.embedder_id == "hashing/dim=256/v1"
    text = r.render()
    assert text.startswith("# Seismograph operating curve") and text.endswith("\n")
    assert "| 1 sigma |" in text and "**1 sigma**" in text
    assert "| 0.25 sigma | 0.0" in text and "30/30" in text
    assert "| 20% |" in text and "## Gradual drift" in text
    assert "false alarm rate: **0.0008**" in text
    # the scripted null alarm is pre-onset, so it counts as an alarm point but not a detection
    assert "runs raising at least one false alarm: 0/30" in text
    assert "alarm points: 1" in text
    assert "<svg" in r.svg


def test_run_suite_reports_floor_not_reached_and_dash_latency(monkeypatch):
    monkeypatch.setattr(golden, "run_scenario",
                        _scripted(99.0, flake_detect=False, drift_detect=False))
    r = golden.run_suite(30)
    assert r.detection_floor is None
    text = r.render()
    assert "**not reached within the swept range**" in text
    assert "| 0/30 | 0.00 |" in text and "| - |" in text
    assert r.false_alarm_rate == 0.0


# -------------------------------------------------------------- acceptance ---
def _passing_report(monkeypatch):
    monkeypatch.setattr(golden, "run_scenario", _scripted(1.0))
    return golden.run_suite(30)


def test_acceptance_passes_on_good_curve(monkeypatch):
    r = _passing_report(monkeypatch)
    results = golden.acceptance(r)
    assert len(results) == 5 and all(ok for _, _, ok in results)
    assert results[2][1] == "0.0000"
    assert golden.thresholds_met(r) is True


def test_acceptance_flags_each_failure(monkeypatch):
    r = _passing_report(monkeypatch)
    weak = dataclasses.replace(r.shift[-1], sensitivity=0.5)
    bad_shift = dataclasses.replace(r, shift=r.shift[:-1] + [weak])
    names = {n: ok for n, _, ok in golden.acceptance(bad_shift)}
    assert names["sensitivity at 3 sigma >= 0.9"] is False
    assert golden.thresholds_met(bad_shift) is False

    weak_flake = dataclasses.replace(r.flake[-1], sensitivity=0.1)
    bad_flake = dataclasses.replace(r, flake=r.flake[:-1] + [weak_flake])
    assert [ok for n, _, ok in golden.acceptance(bad_flake) if "flake" in n] == [False]

    noisy = dataclasses.replace(r, false_alarm_rate=0.5)
    assert [ok for n, _, ok in golden.acceptance(noisy) if n.startswith("false alarm")] == [False]

    dip = dataclasses.replace(r.shift[3], sensitivity=0.0)
    non_mono = dataclasses.replace(r, shift=r.shift[:3] + [dip] + r.shift[4:])
    assert [ok for n, _, ok in golden.acceptance(non_mono) if "non-decreasing" in n] == [False]

    few = dataclasses.replace(r.null, runs=3)
    thin = dataclasses.replace(r, null=few)
    assert [ok for n, _, ok in golden.acceptance(thin) if "non-zero sample" in n] == [False]
    zero_pts = dataclasses.replace(r.null, total_points=0)
    assert golden.thresholds_met(dataclasses.replace(r, null=zero_pts)) is False
