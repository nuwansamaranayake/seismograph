"""The full invariant set, proven on planted defects.

Each simulator carries exactly one defect. The claim under test is not "the code runs" but
"each defect trips the invariant that owns it and no other, and a healthy system trips
none". That is the property a release gate is trusted for.
"""
import pytest

from app.engine.canonicalize import canonicalize, monotonic_violation_rate
from app.engine.contracts import Perturbation, compile_plan, load_contract
from app.engine.embedding import HashingEmbedder
from app.engine.execute import NothingMeasured, execute_plan
from app.engine.sampler import Sample, collect, collect_ladder
from app.engine.suts import DEMO_SUTS, SUT_CATALOG, BimodalSUT

LADDER = [f"Customer bought a blender {d} days ago, unopened. Are they refund eligible?"
          for d in (5, 20, 29, 40, 47, 60)]

FULL_CONTRACT = """
contract: refund-full-invariants
subject: support-agent
invariants:
  - field: eligibility_decision
    under: [repeat_run, irrelevant_context, reordering, format]
    relation: equal
  - field: cited_policy_ids
    under: [repeat_run]
    relation: jaccard_at_least
    threshold: 0.85
  - field: eligibility_decision
    under: [monotonic]
    relation: monotonic
    order: [eligible, ineligible]
allowed_variation:
  - field: response_wording
    rule: semantically_equivalent
run_policy: {samples: 12, configs: 1, confidence: 0.95}
gate: {max_decision_flip_rate: 0.01}
probes:
  - id: refund-basic
    input: "Customer bought a blender 12 days ago, unopened. Are they refund eligible?"
    ladder:
""" + "".join(f'      - "{rung}"\n' for rung in LADDER)


def _run(sut_name: str, t: int = 0):
    contract = load_contract(FULL_CONTRACT)
    plan = compile_plan(contract)
    return execute_plan(contract, plan.entries, DEMO_SUTS[sut_name], t=t, seed=7,
                        embedder=HashingEmbedder())


def _flip_by_perturbation(outcome) -> dict[str, float]:
    return {c.metrics.perturbation: max(c.metrics.flip_rate.values()) for c in outcome.cells}


def test_the_plan_has_one_cell_per_declared_perturbation():
    plan = compile_plan(load_contract(FULL_CONTRACT))
    assert [e.perturbation.value for e in plan.entries] == [
        "format", "irrelevant_context", "monotonic", "reordering", "repeat_run"]


@pytest.mark.parametrize("healthy", ["stable", "policy"])
def test_a_healthy_system_trips_no_invariant(healthy):
    outcome = _run(healthy)
    assert outcome.decision == "pass" and outcome.reasons == ()
    assert set(_flip_by_perturbation(outcome).values()) == {0.0}
    assert outcome.worst_cell is None


@pytest.mark.parametrize("sut,owner", [
    ("distractible", "irrelevant_context"),
    ("order-sensitive", "reordering"),
    ("format-sensitive", "format"),
    ("non-monotonic", "monotonic"),
])
def test_each_planted_defect_trips_its_own_invariant_and_no_other(sut, owner):
    outcome = _run(sut)
    flips = _flip_by_perturbation(outcome)
    assert flips.pop(owner) > 0.01, f"{sut} was not caught by {owner}"
    assert set(flips.values()) == {0.0}, f"{sut} leaked into {flips}"
    assert outcome.decision == "block"
    assert outcome.worst_cell["perturbation"] == owner
    assert SUT_CATALOG[sut]["planted_defect"] is not None


def test_a_consistent_wrong_answer_is_caught_because_cells_compare_to_the_seed():
    """Every reordering of a two-sentence probe is the same string. A cell judged against
    itself would report perfect agreement while every answer is wrong."""
    outcome = _run("order-sensitive")
    assert _flip_by_perturbation(outcome)["reordering"] == 1.0


def test_every_registered_simulator_is_described():
    assert set(SUT_CATALOG) == set(DEMO_SUTS)
    assert all(entry["summary"] for entry in SUT_CATALOG.values())


def test_time_based_defects_are_quiet_before_their_onset_and_loud_after():
    assert _run("flaky", t=0).worst_malformed_rate == 0.0
    late = _run("flaky", t=14)
    assert late.worst_malformed_rate > 0.0 and late.decision == "block"
    assert any("malformed rate" in r for r in late.reasons)


def test_a_cited_policy_shift_fails_its_jaccard_threshold():
    contract = load_contract(FULL_CONTRACT.replace("threshold: 0.85", "threshold: 0.99"))
    plan = compile_plan(contract)
    outcome = execute_plan(contract, plan.entries, BimodalSUT(onset=0, share=0.3), t=1, seed=3,
                           embedder=HashingEmbedder())
    assert outcome.jaccard_failures, "expected a Jaccard failure at the stricter threshold"
    failure = outcome.jaccard_failures[0]
    assert failure["field"] == "cited_policy_ids" and failure["jaccard_mean"] < 0.99
    assert outcome.decision == "block"


# --------------------------------------------------------------------------- #
# contract rules for the new perturbations
# --------------------------------------------------------------------------- #
def test_reordering_on_a_one_sentence_probe_is_refused_naming_the_probe():
    text = FULL_CONTRACT.replace(
        '"Customer bought a blender 12 days ago, unopened. Are they refund eligible?"\n    ladder',
        '"Is a 12 day old blender refundable?"\n    ladder')
    with pytest.raises(ValueError, match="probe 'refund-basic': reordering needs"):
        load_contract(text)


def test_a_monotonic_invariant_needs_an_order_a_ladder_and_its_own_perturbation():
    with pytest.raises(ValueError, match="requires `order`"):
        load_contract(FULL_CONTRACT.replace("    order: [eligible, ineligible]\n", ""))
    with pytest.raises(ValueError, match="pairs with `under: \\[monotonic\\]`"):
        load_contract(FULL_CONTRACT.replace("under: [monotonic]", "under: [repeat_run]"))
    with pytest.raises(ValueError, match="at least one probe with a ladder"):
        load_contract(FULL_CONTRACT.split("    ladder:")[0])
    with pytest.raises(ValueError, match="takes no order"):
        load_contract(FULL_CONTRACT.replace("    threshold: 0.85", "    threshold: 0.85\n    order: [a, b]"))


def test_a_ladder_needs_two_rungs_and_text_perturbations_need_text():
    one_rung = FULL_CONTRACT.split("    ladder:")[0] + '    ladder: ["only one rung. Really?"]\n'
    with pytest.raises(ValueError, match="at least two rungs"):
        load_contract(one_rung)
    with pytest.raises(ValueError, match="need a text input"):
        load_contract(FULL_CONTRACT.split("    ladder:")[0].replace(
            'input: "Customer bought a blender 12 days ago, unopened. Are they refund eligible?"',
            "input: {days: 12}") + "    ladder: [\"a. b?\", \"c. d?\"]\n")


def test_only_laddered_probes_get_a_monotonic_cell():
    text = FULL_CONTRACT + (
        '  - id: refund-edge\n'
        '    input: "Customer bought a blender 31 days ago, opened box. Are they refund eligible?"\n')
    plan = compile_plan(load_contract(text))
    monotonic = [e.probe_id for e in plan.entries if e.perturbation is Perturbation.monotonic]
    assert monotonic == ["refund-basic"]


# --------------------------------------------------------------------------- #
# sampler and metric edges
# --------------------------------------------------------------------------- #
def _entry(perturbation: str):
    plan = compile_plan(load_contract(FULL_CONTRACT))
    return next(e for e in plan.entries if e.perturbation.value == perturbation)


def test_collect_refuses_a_monotonic_cell_and_ladder_refuses_one_rung():
    with pytest.raises(ValueError, match="use collect_ladder"):
        collect(_entry("monotonic"), "x", DEMO_SUTS["policy"], t=0, seed=1)
    with pytest.raises(ValueError, match="at least two rungs"):
        collect_ladder(_entry("monotonic"), ["only"], DEMO_SUTS["policy"], t=0, seed=1)


def _sample(decision: str | None) -> Sample:
    parsed = None if decision is None else {"eligibility_decision": decision,
                                            "cited_policy_ids": ["POL-7"]}
    return Sample("p", "monotonic", "in", "raw", parsed)


def test_monotonic_violation_rate_counts_backward_steps_and_unplaceable_rungs():
    order = ["eligible", "ineligible"]
    rungs = [[_sample("eligible")], [_sample("ineligible")], [_sample("eligible")]]
    assert monotonic_violation_rate(rungs, "eligibility_decision", order) == 0.5
    unknown = [[_sample("eligible")], [_sample("maybe")]]
    assert monotonic_violation_rate(unknown, "eligibility_decision", order) == 1.0
    malformed = [[_sample("eligible")], [_sample(None)]]
    assert monotonic_violation_rate(malformed, "eligibility_decision", order) == 1.0
    with pytest.raises(ValueError, match="at least two rungs"):
        monotonic_violation_rate(rungs[:1], "eligibility_decision", order)


def test_a_rung_tie_resolves_toward_the_earlier_value_in_the_order():
    tie = [[_sample("eligible"), _sample("ineligible")], [_sample("ineligible")]]
    assert monotonic_violation_rate(tie, "eligibility_decision", ["eligible", "ineligible"]) == 0.0


def test_an_unparseable_seed_reads_as_a_violated_invariant_not_a_quiet_pass():
    variants = [_sample("eligible")]
    metrics = canonicalize(variants, ["eligibility_decision"], ["cited_policy_ids"], "",
                           HashingEmbedder(), reference=[_sample(None)])
    assert metrics.flip_rate == {"eligibility_decision": 1.0}
    assert metrics.jaccard_mean == {"cited_policy_ids": 0.0}


def test_a_cell_with_nothing_readable_is_violated_whether_or_not_malformed_is_tolerated():
    """All variants malformed against a good seed, and all samples malformed with no seed:
    there is nothing to compare, so the invariant is reported broken, never as 0.0."""
    fields = (["eligibility_decision"], ["cited_policy_ids"], "", HashingEmbedder())
    perturbed = canonicalize([_sample(None)], *fields, reference=[_sample("eligible")])
    repeat = canonicalize([_sample(None), _sample(None)], *fields)
    for metrics in (perturbed, repeat):
        assert metrics.malformed_rate == 1.0
        assert metrics.flip_rate == {"eligibility_decision": 1.0}
        assert metrics.jaccard_mean == {"cited_policy_ids": 0.0}


# --------------------------------------------------------------------------- #
# paraphrase cells and the empty run
# --------------------------------------------------------------------------- #
PARAPHRASE_ONLY = """
contract: paraphrase-only
subject: support-agent
invariants:
  - field: eligibility_decision
    under: [paraphrase]
    relation: equal
run_policy: {samples: 4, configs: 1, confidence: 0.95}
gate: {max_decision_flip_rate: 0.0, max_second_mode_share: 0.2}
probes:
  - id: p1
    input: "Customer bought a blender 12 days ago, unopened. Are they refund eligible?"
"""


def test_a_run_that_measures_nothing_raises_instead_of_passing():
    contract = load_contract(PARAPHRASE_ONLY)
    with pytest.raises(NothingMeasured, match="no executable plan cells"):
        execute_plan(contract, compile_plan(contract).entries, DEMO_SUTS["stable"],
                     t=0, seed=1, embedder=HashingEmbedder())


def test_paraphrase_cells_run_once_variants_exist_and_compare_to_the_seed():
    contract = load_contract(PARAPHRASE_ONLY)
    entries = compile_plan(contract).entries
    variants = {"p1": ["A blender was purchased 12 days ago and is unopened. Refund?",
                       "Refund question. The blender is 40 days old."]}
    good = execute_plan(contract, entries, DEMO_SUTS["policy"], t=0, seed=1,
                        embedder=HashingEmbedder(), paraphrases={"p1": variants["p1"][:1]})
    assert good.decision == "pass" and good.skipped == ()
    bad = execute_plan(contract, entries, DEMO_SUTS["policy"], t=0, seed=1,
                       embedder=HashingEmbedder(), paraphrases=variants)
    assert bad.worst_flip_rate == 0.5 and bad.decision == "block"
    assert any("second mode above" in r for r in bad.reasons)
    assert bad.evidence()["second_modes"][0]["share"] == 0.5


def test_skipped_cells_are_reported_with_their_reason():
    text = PARAPHRASE_ONLY.replace("under: [paraphrase]", "under: [paraphrase, repeat_run]")
    contract = load_contract(text)
    outcome = execute_plan(contract, compile_plan(contract).entries, DEMO_SUTS["stable"],
                           t=0, seed=1, embedder=HashingEmbedder())
    assert outcome.decision == "pass"
    assert outcome.skipped == ({"probe": "p1", "perturbation": "paraphrase",
                                "reason": "no accepted paraphrase variants generated yet"},)
    assert outcome.evidence()["cells"] == 1
