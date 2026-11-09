"""Outcome modes: the second mode an average conceals, found without a model."""
import random

import pytest

from app.engine.contracts import Perturbation, PlanEntry
from app.engine.modes import MALFORMED, MODE_NOISE_FLOOR, cluster_modes, from_json, pool
from app.engine.sampler import Sample, collect
from app.engine.suts import DEMO_SUTS, BimodalSUT

FIELDS = ["eligibility_decision", "cited_policy_ids"]


def _cell(sut, t: int, seed: int = 5, samples: int = 40) -> list[Sample]:
    entry = PlanEntry(probe_id="p", perturbation=Perturbation.repeat_run,
                      invariant_fields=FIELDS, samples=samples, configs=1)
    return collect(entry, "Customer bought a blender 12 days ago. Refund?", sut, t=t, seed=seed)


def test_a_stable_system_has_exactly_one_mode():
    report = cluster_modes(_cell(DEMO_SUTS["stable"], t=0), FIELDS)
    assert len(report.modes) == 1
    assert report.modes[0].share == 1.0
    assert report.second_mode_share == 0.0 and report.second_mode_low == 0.0
    assert report.second_mode_detected is False
    assert report.modes[0].signature == {"eligibility_decision": "eligible",
                                         "cited_policy_ids": ["POL-7"]}


def test_wording_differences_do_not_split_a_mode():
    """StableSUT varies its wording across three phrasings. Wording is allowed variation,
    not an invariant field, so it must not create modes."""
    samples = _cell(DEMO_SUTS["stable"], t=0)
    assert len({s.parsed["response_wording"] for s in samples}) > 1
    assert len(cluster_modes(samples, FIELDS).modes) == 1


def test_the_planted_second_mode_is_invisible_to_the_flip_rate_and_visible_as_a_mode():
    sut = BimodalSUT(onset=0, share=0.25)
    samples = _cell(sut, t=3)
    decisions = {s.parsed["eligibility_decision"] for s in samples}
    assert decisions == {"eligible"}, "the decision never flips: flip rate is 0"
    report = cluster_modes(samples, FIELDS)
    assert len(report.modes) == 2
    second = report.modes[1]
    assert second.signature["cited_policy_ids"] == ["POL-12", "POL-7"]
    assert "goodwill" in second.representative
    assert report.second_mode_detected is True
    assert report.second_mode_low > MODE_NOISE_FLOOR


def test_one_stray_sample_is_not_reported_as_a_mode():
    samples = _cell(DEMO_SUTS["stable"], t=0, samples=10)
    stray = Sample("p", "repeat_run", "in", '{"eligibility_decision": "ineligible"}',
                   {"eligibility_decision": "ineligible"})
    report = cluster_modes(samples[:9] + [stray], FIELDS)
    assert len(report.modes) == 2 and report.second_mode_share == 0.1
    assert report.second_mode_detected is False, "1 of 10 does not clear the noise floor"


def test_pooling_a_window_reveals_a_small_persistent_mode():
    """At a 10% share a single 10-sample run rarely proves anything. The same mode key
    across a window of runs does."""
    sut = BimodalSUT(onset=0, share=0.10)
    reports = [cluster_modes(_cell(sut, t=t, samples=10), FIELDS) for t in range(12)]
    pooled = pool(reports)
    assert pooled.n == 120
    assert len(pooled.modes) == 2
    assert pooled.second_mode_detected is True
    assert 0.03 < pooled.second_mode_share < 0.20
    assert sum(m.count for m in pooled.modes) == 120


def test_the_same_mode_has_the_same_key_in_every_run():
    sut = BimodalSUT(onset=0, share=0.5)
    a = cluster_modes(_cell(sut, t=1), FIELDS)
    b = cluster_modes(_cell(sut, t=2, seed=99), FIELDS)
    assert {m.key for m in a.modes} == {m.key for m in b.modes}


def test_malformed_output_is_a_mode_of_its_own_and_all_malformed_is_one_mode():
    bad = Sample("p", "repeat_run", "in", "not json", None)
    only_bad = cluster_modes([bad, bad, bad], FIELDS)
    assert [m.key for m in only_bad.modes] == [MALFORMED]
    assert only_bad.modes[0].share == 1.0 and only_bad.second_mode_detected is False
    mixed = cluster_modes(_cell(DEMO_SUTS["stable"], t=0, samples=4) + [bad] * 4, FIELDS)
    assert {m.key for m in mixed.modes} >= {MALFORMED}
    assert mixed.second_mode_share == 0.5


def test_modes_order_by_count_then_key_and_ties_are_stable():
    rng = random.Random(1)
    samples = _cell(BimodalSUT(onset=0, share=0.5), t=0, samples=40)
    rng.shuffle(samples)
    again = list(samples)
    random.Random(2).shuffle(again)
    assert cluster_modes(samples, FIELDS).modes[0].key == cluster_modes(again, FIELDS).modes[0].key
    assert [m.count for m in cluster_modes(samples, FIELDS).modes] == sorted(
        (m.count for m in cluster_modes(samples, FIELDS).modes), reverse=True)


def test_a_report_survives_json_storage():
    report = cluster_modes(_cell(BimodalSUT(onset=0, share=0.3), t=0), FIELDS)
    assert from_json(report.to_json()) == report


def test_empty_inputs_are_refused():
    with pytest.raises(ValueError, match="empty sample set"):
        cluster_modes([], FIELDS)
    with pytest.raises(ValueError, match="nothing to pool"):
        pool([])
