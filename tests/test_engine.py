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


def test_run8_signals_once_per_run():
    baseline = [0.02, 0.03, 0.02, 0.03, 0.02, 0.03, 0.02, 0.03] * 4
    chart = IndividualsChart(baseline)
    points = [chart.add(t, chart.center + chart.sigma) for t in range(12)]
    # One run of 12 same-side points is ONE signal (at its 8th point), not five.
    assert [p.rule for p in points].count("run8") == 1


def test_pchart_flags_burst_and_tolerates_clean():
    chart = PChart([0.0] * 30, n=20)
    assert not chart.add(0, 0.05).alarm          # one flake in 20 is not an alarm
    assert chart.add(1, 0.25).alarm              # a real burst is


def test_wilson_refuses_a_rate_over_zero_trials():
    # A rate computed from nothing is the vacuous pass this suite exists to prevent.
    from app.engine.golden import wilson
    with pytest.raises(ValueError, match="zero trials"):
        wilson(0, 0)
    p, lo, hi = wilson(30, 30)
    assert p == 1.0 and lo < 1.0 and hi == 1.0        # interval stays honest at the boundary


def test_summarize_rejects_empty_cells():
    from app.engine.golden import summarize
    with pytest.raises(ValueError, match="zero runs"):
        summarize("shift:1.0", "label", [])


def test_defects_are_sized_in_sigma_of_the_healthy_process():
    from app.engine.golden import HEALTHY_FLIP_P, flip_p_for_sigma, sigma_healthy
    s = sigma_healthy()
    assert 0.02 < s < 0.05                            # analytic SD for p=0.04, n=40
    assert flip_p_for_sigma(0) == HEALTHY_FLIP_P
    assert flip_p_for_sigma(2) == pytest.approx(HEALTHY_FLIP_P + 2 * s)


def test_suite_refuses_underpowered_cells():
    from app.engine.golden import run_suite
    with pytest.raises(ValueError, match="usable interval"):
        run_suite(runs_per_cell=5)


def test_numeric_drift_is_rejected_by_the_back_check():
    """An embedding is nearly blind to a changed digit: '12 days' vs '120 days' scored
    0.956 and was accepted until a planted negative control caught it."""
    from app.engine.metamorphic import generate_paraphrases, introduces_numbers
    from app.engine.embedding import HashingEmbedder

    seed = "Customer bought a blender 12 days ago, unopened. Are they refund eligible?"
    assert introduces_numbers(seed, seed.replace("12", "120")) is True
    assert introduces_numbers(seed, "Customer bought a blender twelve days ago.") is False
    assert introduces_numbers("Total 1,200 units", "Total 1200 units") is False

    class Stub:
        def complete(self, *, model, messages, json_schema=None, temperature=0.0):
            return {"paraphrases": [seed.replace("12", "120")]}

    [v] = generate_paraphrases(Stub(), "m", seed, 1, HashingEmbedder())
    assert v.accepted is False and v.reason == "numeric_drift"
