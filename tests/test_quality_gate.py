"""The quality gate's own rules. A gate that cannot fail is not a gate, so the failing
paths are what is tested: one weak component fails the whole report, and a component
that could not be measured scores zero instead of disappearing."""
import importlib.util
from pathlib import Path

SPEC = importlib.util.spec_from_file_location(
    "quality", Path(__file__).resolve().parent.parent / "scripts" / "quality.py")
quality = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(quality)


def test_a_finding_costs_a_point_and_the_score_never_goes_negative():
    assert quality._penalty(0) == 100.0
    assert quality._penalty(3) == 97.0
    assert quality._penalty(5) == 95.0 < quality.FLOOR
    assert quality._penalty(400) == 0.0


def test_the_floor_is_inclusive_and_one_weak_component_fails_the_gate():
    at_floor = quality._component("a", 96.0, "at the floor")
    under = quality._component("b", 95.99, "just under")
    assert at_floor["ok"] is True and under["ok"] is False
    components = [quality._component("c", 100.0, "perfect")] * 8 + [under]
    assert all(c["ok"] for c in components) is False, "eight perfect scores do not buy back one miss"


def test_an_unmeasured_component_scores_zero_and_says_why():
    hole = quality._unmeasured("frontend tests", "npx missing")
    assert hole["score"] == 0.0 and hole["ok"] is False
    assert hole["detail"] == "NOT MEASURED: npx missing"


def test_the_report_states_the_minimum_as_the_gate_and_marks_the_failing_row():
    report = {
        "generated_at": "2026-11-09T00:00:00Z", "commit": "abc1234", "passed": False,
        "minimum": 91.0, "score": 99.0,
        "components": [quality._component("backend lint", 91.0, "9 ruff findings"),
                       quality._component("backend tests", 100.0, "10 of 10 passed")],
    }
    text = quality.render(report)
    assert "**Gate: FAIL.** The lowest component is 91.00 against a floor of 96." in text
    assert "| backend lint | 91.00 | NO | 9 ruff findings |" in text
    assert "| backend tests | 100.00 | yes | 10 of 10 passed |" in text


def test_the_lint_rules_scored_are_the_rules_pyproject_pins():
    import tomllib

    config = tomllib.loads((quality.REPO / "pyproject.toml").read_text(encoding="utf-8"))
    lint = config["tool"]["ruff"]["lint"]
    assert set(quality.RUFF_SELECT.split(",")) == set(lint["select"])
    assert quality.RUFF_IGNORE.split(",") == lint["ignore"]
    assert lint["mccabe"]["max-complexity"] == quality.MAX_COMPLEXITY
