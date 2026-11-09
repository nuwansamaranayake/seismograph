"""Remaining branches of app.runner: judge layers, baselines, report, session store."""
from __future__ import annotations

import json
from datetime import date

import pytest
import sqlalchemy as sa

from app import db, runner
from app.runner import (
    LayerOutcome,
    RunResult,
    load_baseline,
    report_markdown,
    run_suite,
    write_baseline,
)
from app.suite import Case, Layer, Profile, Suite
from app.targets import CallRecord

DAY = date(2026, 9, 19)
REF = {"lagna": "Leo", "moon_nakshatra": "Magha", "moon_pada": 2,
       "mahadasha_lord": "Ketu", "mahadasha_years_remaining": 3.4}


_ROOT = None


@pytest.fixture(autouse=True)
def _root(tmp_path):
    global _ROOT
    _ROOT = tmp_path


def _suite(layers, repeats=1, n_cases=1):
    cases = tuple(Case(f"c{i}", "synthetic", {"i": i}, REF) for i in range(n_cases))
    return Suite("s", "v1", "tid", None, tuple(layers), cases,
                 {"p": Profile("p", repeats, None)}, root=_ROOT)


class Target:
    def __init__(self, outputs, target_id="T"):
        self.target_id = target_id
        self.outputs = list(outputs)
        self.bodies = []

    def call(self, body, json_path=None):
        self.bodies.append(body)
        out = self.outputs.pop(0)
        if isinstance(out, str):
            return CallRecord(self.target_id, "http", "POST /", "h", 1, error=out)
        return CallRecord(self.target_id, "http", "POST /", "h", 1, raw_response=out)


class Judge:
    def __init__(self, replies):
        self.replies = list(replies)
        self.models = []

    def complete(self, *, model, messages, json_schema=None, temperature=0.0):
        self.models.append(model)
        return self.replies.pop(0)


GOOD_EXTRACT = dict(REF)


def test_run_layer_unknown_check_type_is_incomplete():
    layer = Layer("odd", "telepathy", {})
    result = run_suite(_suite([layer]), Target([{"a": 1}]), Profile("p", 1, None), on=DAY)
    assert result.outcomes == []
    assert result.incomplete == ["c0::odd: unknown check type 'telepathy'"]


@pytest.mark.parametrize("check", ["grounded", "rubric"])
def test_judge_layers_without_judge_are_incomplete_not_passed(check):
    layer = Layer("j", check, {})
    result = run_suite(_suite([layer]), Target([{"a": 1}]), Profile("p", 1, None), on=DAY)
    assert result.outcomes == []
    assert "needs a judge model" in result.incomplete[0]
    # judge object present but model id missing is also incomplete
    result = run_suite(_suite([layer]), Target([{"a": 1}]), Profile("p", 1, None), on=DAY,
                       judge=Judge([]), judge_model=None)
    assert "SEISMO_JUDGE_MODEL is unset" in result.incomplete[0]


def test_grounded_layer_reads_prose_field_and_passes():
    layer = Layer("g", "grounded", {"prose_field": "prose"})
    judge = Judge([GOOD_EXTRACT])
    result = run_suite(_suite([layer]), Target([{"prose": "Leo lagna"}]),
                       Profile("p", 1, None), on=DAY, judge=judge, judge_model="jm")
    assert [o.passed for o in result.outcomes] == [True]
    assert judge.models == ["jm"]
    assert result.header["judge_model"] == "jm"
    assert result.header["rubric_version"] == runner.RUBRIC_VERSION


def test_grounded_layer_failure_carries_reasons():
    bad = dict(GOOD_EXTRACT, lagna="Virgo")
    layer = Layer("g", "grounded", {})
    result = run_suite(_suite([layer]), Target([{"x": 1}]), Profile("p", 1, None), on=DAY,
                       judge=Judge([bad]), judge_model="jm")
    (o,) = result.outcomes
    assert not o.passed and "lagna" in o.reasons[0]
    assert result.failures == [o]


def test_rubric_layer_uses_serialised_output_without_prose_field():
    layer = Layer("r", "rubric", {})
    out = {"text": "steady discipline"}
    judge = Judge([{"score": 5, "evidence": "steady discipline"}])
    result = run_suite(_suite([layer]), Target([out]), Profile("p", 1, None), on=DAY,
                       judge=judge, judge_model="jm")
    assert result.outcomes[0].passed and result.outcomes[0].check_type == "rubric"


def test_target_error_becomes_failed_outcome_and_skips_layers():
    layer = Layer("a", "assert", {})
    result = run_suite(_suite([layer], repeats=3), Target(["boom"]),
                       Profile("p", 3, None), on=DAY)
    (o,) = result.outcomes
    assert (o.layer, o.passed) == ("target", False)
    assert o.reasons == ["target call failed: boom"]


def test_repeats_determinism_pass_and_fail():
    layer = Layer("a", "assert", {})
    same = run_suite(_suite([layer], 2), Target([{"v": 1}, {"v": 1}]),
                     Profile("p", 2, None), on=DAY)
    assert [(o.layer, o.passed) for o in same.outcomes] == [
        ("determinism", True), ("a", True)]
    diff = run_suite(_suite([layer], 2), Target([{"v": 1}, {"v": 2}]),
                     Profile("p", 2, None), on=DAY)
    det = diff.outcomes[0]
    assert det.layer == "determinism" and not det.passed
    assert "2 repeats did not produce identical output" in det.reasons[0]


def test_drift_unbaselined_and_target_id_from_target():
    layer = Layer("a", "assert", {"regex_absent": [{"name": "bad", "pattern": "boom"}]})
    base = {"verdicts": {"c0::a": True, "c1::a": False}}
    target = Target([{"v": "boom"}, {"v": "boom"}, {"v": "ok"}], target_id="fixture-9")
    result = run_suite(_suite([layer], n_cases=3), target, Profile("p", 1, None), on=DAY,
                       baseline=base)
    assert result.target_id == "fixture-9"
    assert result.drifted == ["c0::a"]            # was passing, now fails
    assert result.unbaselined == ["c2::a"]        # no baseline entry
    # c1 was already failing in the baseline and still fails: not drift
    assert "c1::a" not in result.drifted


def test_session_persists_every_call_record():
    engine = sa.create_engine("sqlite://", poolclass=sa.pool.StaticPool)
    db.metadata.create_all(engine)
    db.set_engine_for_tests(engine)
    session = db.get_session()
    layer = Layer("a", "assert", {})
    result = run_suite(_suite([layer], 2), Target([{"v": 1}, {"v": 1}]),
                       Profile("p", 2, None), on=DAY, session=session)
    assert result.header["stored_in_postgres"] is True
    rows = session.execute(sa.text("select count(*) from target_calls")).scalar()
    assert rows == 2


# ------------------------------------------------------------- baseline ---
def _result():
    r = RunResult("s", "p", "T", {"suite": "s", "profile": "p", "stored_in_postgres": False,
                                  "suite_sha256_16": "abc"})
    r.outcomes = [LayerOutcome("c0", "a", "assert", True),
                  LayerOutcome("c1", "a", "assert", False, ["x | y", "z"])]
    return r


def test_baseline_roundtrip_ignores_volatile_header_keys(tmp_path):
    path = tmp_path / "deep" / "dir" / "b.json"
    r = _result()
    write_baseline(path, r)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["verdicts"] == {"c0::a": True, "c1::a": False}
    assert "profile" not in data["header"] and "stored_in_postgres" not in data["header"]
    assert path.read_text(encoding="utf-8").endswith("\n")
    header = dict(r.header, profile="other", stored_in_postgres=True)
    assert load_baseline(path, header)["verdicts"] == data["verdicts"]


def test_baseline_missing_returns_none(tmp_path):
    assert load_baseline(tmp_path / "nope.json", {"suite": "s"}) is None


def test_baseline_header_mismatch_refused(tmp_path):
    path = tmp_path / "b.json"
    write_baseline(path, _result())
    with pytest.raises(RuntimeError, match=r"header mismatch on \['suite_sha256_16'\]"):
        load_baseline(path, dict(_result().header, suite_sha256_16="zzz"))


# --------------------------------------------------------------- report ---
def test_report_markdown_sections():
    r = _result()
    r.drifted = ["c0::a"]
    r.incomplete = ["c9::j: needs judge"]
    r.unbaselined = ["c1::a"]
    md = report_markdown(r)
    assert md.startswith("# Seismograph suite run — s / p")
    assert "checks run: 2 | failed: 1 | drifted: 1 | incomplete: 1" in md
    assert "| c0 | a | assert | PASS | - |" in md
    assert "| c1 | a | assert | FAIL | x \\| y; z |" in md
    assert "## drift vs baseline\n- c0::a" in md
    assert "## incomplete layers\n- c9::j: needs judge" in md
    assert "## not in baseline\n- c1::a" in md
    assert md.endswith("\n")


def test_report_markdown_omits_empty_sections():
    r = _result()
    md = report_markdown(r)
    assert "drift vs baseline" not in md and "incomplete layers" not in md
    assert "not in baseline" not in md
