"""Judge panel arithmetic: agreement with anchors, quarantine, and the panel verdict."""
import json
from pathlib import Path

import pytest

from app.engine.judges import (
    AGREEMENT_FLOOR,
    Agreement,
    agreement,
    load_anchors,
    panel_verdict,
    quarantine,
)

ANCHOR_FILE = Path(__file__).resolve().parent.parent / "data" / "checks" / "judge_agreement_set.v1.json"
ANCHORS = {f"a{i}": ("clean" if i % 2 else "violation") for i in range(10)}


def test_the_shipped_anchor_set_loads_only_its_labelled_items():
    anchors = load_anchors(ANCHOR_FILE)
    raw = json.loads(ANCHOR_FILE.read_text(encoding="utf-8"))["items"]
    assert len(anchors) == sum(1 for i in raw if "gold_label" in i) > 0
    assert set(anchors.values()) == {"clean", "planted"}


def test_an_anchor_set_without_labels_is_refused(tmp_path):
    path = tmp_path / "anchors.json"
    path.write_text(json.dumps([{"id": "x"}]), encoding="utf-8")
    with pytest.raises(ValueError, match="no labelled items"):
        load_anchors(path)
    path.write_text(json.dumps([{"id": "x", "gold_label": "clean"}]), encoding="utf-8")
    assert load_anchors(path) == {"x": "clean"}


def test_perfect_agreement():
    result = agreement(dict(ANCHORS), ANCHORS)
    assert (result.n, result.agree, result.rate, result.kappa) == (10, 10, 1.0, 1.0)
    assert result.low < 0.8 and result.high == pytest.approx(1.0)


def test_partial_agreement_reports_rate_interval_and_kappa():
    verdicts = dict(ANCHORS) | {"a0": "clean", "a2": "clean"}      # two violations missed
    result = agreement(verdicts, ANCHORS)
    assert isinstance(result, Agreement)
    assert (result.n, result.agree, result.rate) == (10, 8, 0.8)
    assert result.low < 0.8 < result.high
    # observed 0.8, chance 0.7*0.5 + 0.3*0.5 = 0.5 -> kappa 0.6
    assert result.kappa == pytest.approx(0.6)


def test_a_judge_that_always_says_clean_has_zero_kappa():
    result = agreement({k: "clean" for k in ANCHORS}, ANCHORS)
    assert result.rate == 0.5 and result.kappa == pytest.approx(0.0)


def test_one_label_on_both_sides_is_full_agreement_not_a_division_by_zero():
    assert agreement({"a1": "clean", "a3": "clean"}, ANCHORS).kappa == 1.0


def test_a_subset_of_anchors_is_scored_on_that_subset():
    assert agreement({"a1": "clean"}, ANCHORS).n == 1


def test_unknown_ids_and_empty_rounds_are_refused():
    with pytest.raises(ValueError, match=r"not in the anchor set: \['zz'\]"):
        agreement({"a1": "clean", "zz": "clean"}, ANCHORS)
    with pytest.raises(ValueError, match="at least one verdict"):
        agreement({}, ANCHORS)


def test_quarantine_below_the_floor():
    assert quarantine([0.9, 0.7], n=10) == (True, "below_floor")
    assert quarantine([AGREEMENT_FLOOR], n=10) == (False, None)
    with pytest.raises(ValueError, match="no calibration rounds"):
        quarantine([], n=10)


def test_drift_is_called_only_with_a_full_baseline_and_only_below_its_lower_limit():
    steady = [0.99] * 8
    # n=200: baseline p-bar 0.99, lower limit about 0.969. 0.85 clears the 0.8 floor and has drifted.
    assert quarantine(steady + [0.85], n=200) == (True, "drift")
    assert quarantine(steady + [0.98], n=200) == (False, None)
    assert quarantine(steady[:7] + [0.85], n=200) == (False, None), "7 rounds is not a baseline"
    assert quarantine(steady + [0.85], n=1) == (False, None), "a p-chart needs n >= 2"


def test_panel_majority_among_active_judges():
    verdict = panel_verdict({"a": "clean", "b": "clean", "c": "violation"}, quarantined=set())
    assert verdict.label == "clean"
    assert verdict.counted == ("a", "b", "c") and verdict.excluded == ()
    assert verdict.reason == "2 of 3 active judges"


def test_a_quarantined_vote_is_excluded_and_named():
    votes = {"a": "clean", "b": "violation", "c": "violation"}
    verdict = panel_verdict(votes, quarantined={"c"})
    assert verdict.label is None and verdict.excluded == ("c",)
    assert verdict.reason == "tie between 'clean' and 'violation'"
    assert panel_verdict(votes, quarantined={"a"}).label == "violation"


def test_a_panel_without_a_quorum_gives_no_verdict():
    verdict = panel_verdict({"a": "clean", "b": "clean"}, quarantined={"a", "b"})
    assert verdict.label is None and verdict.counted == ()
    assert verdict.reason == "0 active judge(s), quorum is 2"
    assert panel_verdict({"a": "clean"}, set(), quorum=1).label == "clean"
