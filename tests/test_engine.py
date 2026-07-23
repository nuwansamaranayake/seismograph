import random

import pytest

from app.engine.canonicalize import canonicalize
from app.engine.charts import IndividualsChart, PChart
from app.engine.contracts import PlanEntry, Perturbation
from app.engine.embedding import HashingEmbedder, cosine
from app.engine.sampler import collect
from app.engine.suts import FlakySUT, JumpSUT, StableSUT


def entry(pert: Perturbation) -> PlanEntry:
    return PlanEntry(
        probe_id="refund-basic", perturbation=pert,
        invariant_fields=["eligibility_decision"], samples=20, configs=1,
    )


def test_hashing_embedder_is_deterministic_and_normalized():
    e = HashingEmbedder()
    [a1], [a2] = e.embed(["refund please"]), e.embed(["refund please"])
    assert a1 == a2
    assert cosine(a1, a2) == pytest.approx(1.0)
    [b] = e.embed(["completely different words entirely"])
    assert cosine(a1, b) < 0.5


def test_sampler_is_replayable_and_parses_json():
    s1 = collect(entry(Perturbation.repeat_run), "input", StableSUT(), t=0, seed=7)
    s2 = collect(entry(Perturbation.repeat_run), "input", StableSUT(), t=0, seed=7)
    assert [x.raw_output for x in s1] == [x.raw_output for x in s2]
    assert all(x.parsed is not None for x in s1)


def test_sampler_refuses_unbuilt_perturbation():
    with pytest.raises(NotImplementedError, match="no generator"):
        collect(entry(Perturbation.reordering), "input", StableSUT(), t=0, seed=7)


def test_paraphrase_cell_requires_variants():
    with pytest.raises(ValueError, match="back-checked variants"):
        collect(entry(Perturbation.paraphrase), "input", StableSUT(), t=0, seed=7)


def test_canonicalize_stable_sut_is_quiet():
    samples = collect(entry(Perturbation.repeat_run), "input", StableSUT(), t=0, seed=7)
    m = canonicalize(samples, ["eligibility_decision"], ["cited_policy_ids"],
                     "response_wording", HashingEmbedder())
    assert m.flip_rate["eligibility_decision"] == 0.0
    assert m.jaccard_mean["cited_policy_ids"] == 1.0
    assert m.malformed_rate == 0.0
    assert 0.0 <= m.semantic_variance < 0.9


def test_canonicalize_measures_planted_flips_and_flakes():
    jump = collect(entry(Perturbation.repeat_run), "input", JumpSUT(onset=0), t=5, seed=7)
    mj = canonicalize(jump, ["eligibility_decision"], [], "response_wording", HashingEmbedder())
    assert mj.flip_rate["eligibility_decision"] > 0.1

    flaky = collect(entry(Perturbation.repeat_run), "input",
                    FlakySUT(onset=0, p=0.3, burst=100), t=5, seed=7)
    mf = canonicalize(flaky, ["eligibility_decision"], [], "response_wording", HashingEmbedder())
    assert mf.malformed_rate > 0.1


def test_individuals_chart_alarms_on_jump_not_on_noise():
    rng = random.Random(3)
    baseline = [0.02 + rng.random() * 0.01 for _ in range(30)]
    chart = IndividualsChart(baseline)
    quiet = [chart.add(t, 0.02 + rng.random() * 0.01) for t in range(50)]
    assert not any(p.alarm and p.rule == "we1" for p in quiet)
    assert chart.add(99, 0.35).alarm


def test_individuals_chart_run8_catches_drift():
    baseline = [0.02, 0.03, 0.02, 0.03, 0.02, 0.03, 0.02, 0.03] * 4
    chart = IndividualsChart(baseline)
    alarms = [chart.add(t, chart.center + chart.sigma) for t in range(10)]
    assert any(p.rule == "run8" for p in alarms)


def test_pchart_flags_burst_and_tolerates_clean():
    chart = PChart([0.0] * 30, n=20)
    assert not chart.add(0, 0.05).alarm          # one flake in 20 is not an alarm
    assert chart.add(1, 0.25).alarm              # a real burst is
