"""Unit tests for the three check types, and a freshness test on the labelled sets.

The judge-backed types are tested against a hand-written stub gateway, not a
mocking library: scripts/gates.py `_g1_c3_no_mock_targets` forbids a mocking
import anywhere in app/ or scripts/, and a stub written here keeps the test
honest about exactly what the model is assumed to return.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.checks import (
    RUBRIC_PASS_SCORE,
    compare_extraction,
    run_assert_check,
    run_grounded_check,
    run_rubric_check,
)

ROOT = Path(__file__).resolve().parent.parent
SETS = ROOT / "data" / "checks"


class StubGateway:
    """Returns a queued reply per call. Asserts the model id is passed through."""

    def __init__(self, replies: list[dict]):
        self._replies = list(replies)
        self.models_used: list[str] = []

    def complete(self, *, model, messages, json_schema=None, temperature=0.0):
        self.models_used.append(model)
        if not self._replies:
            raise AssertionError("StubGateway called more times than it has replies")
        return self._replies.pop(0)


def _assert_set() -> dict:
    return json.loads((SETS / "assert_set.v1.json").read_text(encoding="utf-8"))


REFERENCE = {
    "lagna": "Leo", "moon_nakshatra": "Magha", "moon_pada": 2, "mahadasha_lord": "Ketu",
    "mahadasha_years_remaining": 3.4, "moon_longitude": 123.5833, "language": "en",
}


def _output(**override) -> str:
    body = {
        "reading": "Leo rises with the Moon in Magha pada 2. The Ketu dasha has 3.4 years left.",
        "language": "en",
        "chart": {
            "lagna": "Leo", "moon_nakshatra": "Magha", "moon_pada": 2,
            "mahadasha_lord": "Ketu", "mahadasha_years_remaining": 3.4,
            "moon_longitude": 123.5833,
        },
    }
    for path, value in override.items():
        target, _, leaf = path.rpartition(".")
        node = body
        for part in target.split(".") if target else []:
            node = node[part]
        node[leaf] = value
    return json.dumps(body)


# --------------------------------------------------------------------------- #
# assert
# --------------------------------------------------------------------------- #
def test_assert_passes_a_clean_output():
    outcome = run_assert_check(_output(), _assert_set()["policy"], REFERENCE)
    assert outcome.passed, outcome.reasons


def test_assert_rejects_non_json():
    outcome = run_assert_check("Leo rises.", _assert_set()["policy"], REFERENCE)
    assert not outcome.passed
    assert "not JSON" in outcome.reasons[0]


@pytest.mark.parametrize(
    "override, fragment",
    [
        ({"chart.moon_pada": 5}, "schema"),
        ({"chart.moon_pada": "2"}, "schema"),
        ({"chart.lagna": "Cancer"}, "equals[chart.lagna]"),
        ({"language": "si"}, "equals[language]"),
        ({"chart.moon_longitude": 123.5833 + 0.0333}, "numeric[chart.moon_longitude]"),
    ],
)
def test_assert_catches_each_rule_class(override, fragment):
    outcome = run_assert_check(_output(**override), _assert_set()["policy"], REFERENCE)
    assert not outcome.passed
    assert any(fragment in r for r in outcome.reasons), outcome.reasons


def test_assert_catches_forbidden_and_missing_phrases():
    policy = _assert_set()["policy"]
    gem = run_assert_check(
        _output(reading="Leo rises, Ketu dasha. Wear a blue sapphire set in silver."),
        policy, REFERENCE)
    assert not gem.passed and any("forbidden[gemstone]" in r for r in gem.reasons)

    silent = run_assert_check(
        _output(reading="Leo rises with the Moon in Magha. Patience beats announcement here."),
        policy, REFERENCE)
    assert not silent.passed and any("required[names_the_dasha]" in r for r in silent.reasons)


def test_assert_tolerance_boundary_is_inclusive():
    """One arc-minute exactly is inside tolerance; a hair more is not."""
    policy = _assert_set()["policy"]
    inside = run_assert_check(_output(**{"chart.moon_longitude": 123.5833 + 0.0166}),
                              policy, REFERENCE)
    outside = run_assert_check(_output(**{"chart.moon_longitude": 123.5833 + 0.0170}),
                               policy, REFERENCE)
    assert inside.passed, inside.reasons
    assert not outside.passed


# --------------------------------------------------------------------------- #
# grounded — the comparison is plain code and is tested as plain code
# --------------------------------------------------------------------------- #
def test_compare_extraction_accepts_a_faithful_extraction():
    got = {"lagna": "leo", "moon_nakshatra": "Magha", "moon_pada": 2,
           "mahadasha_lord": "Ketu", "mahadasha_years_remaining": 3.4}
    assert compare_extraction(got, REFERENCE, 0.25) == []


def test_compare_extraction_flags_a_contradiction_and_an_omission():
    got = {"lagna": "Cancer", "moon_nakshatra": "", "moon_pada": 2,
           "mahadasha_lord": "Ketu", "mahadasha_years_remaining": 3.4}
    reasons = compare_extraction(got, REFERENCE, 0.25)
    assert any("lagna" in r and "Cancer" in r for r in reasons)
    assert any("moon_nakshatra" in r and "states nothing" in r for r in reasons)


def test_compare_extraction_respects_the_numeric_tolerance():
    near = {"lagna": "Leo", "moon_nakshatra": "Magha", "moon_pada": 2,
            "mahadasha_lord": "Ketu", "mahadasha_years_remaining": 3.6}
    assert compare_extraction(near, REFERENCE, 0.25) == []
    far = {**near, "mahadasha_years_remaining": 3.7}
    assert compare_extraction(far, REFERENCE, 0.25)


def test_compare_extraction_rejects_the_sentinel_for_a_missing_number():
    got = {"lagna": "Leo", "moon_nakshatra": "Magha", "moon_pada": 2,
           "mahadasha_lord": "Ketu", "mahadasha_years_remaining": -1}
    assert any("nothing usable" in r for r in compare_extraction(got, REFERENCE, 0.25))


def test_grounded_check_passes_the_model_id_through():
    gateway = StubGateway([{
        "lagna": "Leo", "moon_nakshatra": "Magha", "moon_pada": 2,
        "mahadasha_lord": "Ketu", "mahadasha_years_remaining": 3.4,
    }])
    outcome = run_grounded_check(gateway, "vendor/model-x", "Leo rises...", REFERENCE)
    assert outcome.passed
    assert gateway.models_used == ["vendor/model-x"]


# --------------------------------------------------------------------------- #
# rubric — the code decides two things the judge cannot be trusted with
# --------------------------------------------------------------------------- #
READING = ("Leo rises and the Magha Moon wants recognition. The Ketu dasha has three and a "
           "half years left, and it keeps thinning out what you thought you were owed.")


def test_rubric_passes_on_a_high_score_with_a_verbatim_span():
    gateway = StubGateway([{"score": 5, "evidence": "The Ketu dasha has three and a half years left"}])
    assert run_rubric_check(gateway, "vendor/model-x", READING).passed


def test_rubric_fails_a_fabricated_evidence_span():
    gateway = StubGateway([{"score": 5, "evidence": "Wear a blue sapphire on Saturday"}])
    outcome = run_rubric_check(gateway, "vendor/model-x", READING)
    assert not outcome.passed
    assert any("not verbatim" in r for r in outcome.reasons)


def test_rubric_accepts_a_rewrapped_but_real_span():
    gateway = StubGateway([{"score": 4, "evidence": "The Ketu dasha has\n  three and a half\nyears left"}])
    assert run_rubric_check(gateway, "vendor/model-x", READING).passed


def test_rubric_fails_below_the_pass_score():
    gateway = StubGateway([{"score": RUBRIC_PASS_SCORE - 1, "evidence": "Leo rises"}])
    outcome = run_rubric_check(gateway, "vendor/model-x", READING)
    assert not outcome.passed
    assert any("score:" in r for r in outcome.reasons)


def test_rubric_fails_an_out_of_range_score():
    gateway = StubGateway([{"score": 9, "evidence": "Leo rises"}])
    assert not run_rubric_check(gateway, "vendor/model-x", READING).passed


def test_rubric_fails_when_the_judge_quotes_nothing():
    gateway = StubGateway([{"score": 5, "evidence": "  "}])
    outcome = run_rubric_check(gateway, "vendor/model-x", READING)
    assert not outcome.passed
    assert any("quoted nothing" in r for r in outcome.reasons)


# --------------------------------------------------------------------------- #
# the labelled sets themselves
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("name", ["assert", "grounded", "rubric"])
def test_labelled_set_is_balanced_and_large_enough(name):
    data = json.loads((SETS / f"{name}_set.v1.json").read_text(encoding="utf-8"))
    samples = data["samples"]
    clean = [s for s in samples if s["label"] == "clean"]
    planted = [s for s in samples if s["label"] == "planted"]
    assert len(samples) >= 40, "docs/gates-spec.md g2 requires at least 40 samples per type"
    assert len(clean) == len(planted)
    assert {s["subtlety"] for s in planted} == {"blatant", "moderate", "subtle"}
    assert all(s["defect"] for s in planted)
    assert len({s["id"] for s in samples}) == len(samples)


def test_agreement_set_is_disjoint_from_the_measured_sets():
    """Selecting the judge on the samples it is later scored against would make the
    measurement a description of the selection."""
    agreement = json.loads(
        (SETS / "judge_agreement_set.v1.json").read_text(encoding="utf-8"))
    agreement_texts = {i["output"] for i in agreement["items"]}
    for name in ("assert", "grounded", "rubric"):
        data = json.loads((SETS / f"{name}_set.v1.json").read_text(encoding="utf-8"))
        assert not agreement_texts & {s["output"] for s in data["samples"]}


def test_frozen_sets_match_their_builder():
    """A hand-edited label in data/checks/ is a silent change to what every
    sensitivity number means. The builder is the source; the JSON must match it."""
    import scripts.build_check_sets as builder

    for name, build in (
        ("assert", builder.build_assert_set),
        ("grounded", builder.build_grounded_set),
        ("rubric", builder.build_rubric_set),
        ("judge_agreement", builder.build_agreement_set),
    ):
        on_disk = json.loads((SETS / f"{name}_set.v1.json").read_text(encoding="utf-8"))
        rebuilt = build()
        rebuilt.pop("content_sha256_16", None)
        on_disk.pop("content_sha256_16", None)
        assert rebuilt == on_disk, f"{name}_set.v1.json is out of date with its builder"
