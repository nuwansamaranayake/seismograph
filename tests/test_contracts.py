import pytest

from app.engine.contracts import compile_plan, load_contract, Perturbation

CONTRACT_YAML = """
contract: refund-decision-stability
subject: support-agent
invariants:
  - field: eligibility_decision
    under: [paraphrase, repeat_run]
    relation: equal
  - field: cited_policy_ids
    under: [repeat_run]
    relation: jaccard_at_least
    threshold: 0.85
allowed_variation:
  - field: response_wording
    rule: semantically_equivalent
run_policy: {samples: 10, configs: 3, confidence: 0.95}
gate: {max_decision_flip_rate: 0.01}
probes:
  - id: refund-basic
    input: "Customer bought a blender 12 days ago, unopened. Are they refund eligible?"
  - id: refund-edge
    input: "Customer bought a blender 31 days ago, opened box. Are they refund eligible?"
"""


def test_blueprint_contract_parses():
    c = load_contract(CONTRACT_YAML)
    assert c.contract == "refund-decision-stability"
    assert c.run_policy.samples == 10
    assert c.gate.max_decision_flip_rate == 0.01
    assert len(c.probes) == 2


def test_jaccard_requires_threshold():
    bad = CONTRACT_YAML.replace("    threshold: 0.85\n", "")
    with pytest.raises(ValueError, match="threshold"):
        load_contract(bad)


def test_equal_rejects_threshold():
    bad = CONTRACT_YAML.replace(
        "    relation: equal\n", "    relation: equal\n    threshold: 0.5\n", 1
    )
    with pytest.raises(ValueError, match="no threshold"):
        load_contract(bad)


def test_duplicate_probe_ids_rejected():
    bad = CONTRACT_YAML.replace("id: refund-edge", "id: refund-basic")
    with pytest.raises(ValueError, match="unique"):
        load_contract(bad)


def test_plan_is_deterministic():
    p1 = compile_plan(load_contract(CONTRACT_YAML))
    p2 = compile_plan(load_contract(CONTRACT_YAML))
    assert p1.plan_id == p2.plan_id
    assert p1.model_dump() == p2.model_dump()


def test_plan_grid_merges_invariants_per_cell():
    plan = compile_plan(load_contract(CONTRACT_YAML))
    # 2 probes x perturbations {paraphrase, repeat_run} = 4 cells
    assert len(plan.entries) == 4
    repeat_cells = [e for e in plan.entries if e.perturbation is Perturbation.repeat_run]
    # repeat_run covers both invariant fields in one cell
    assert all(
        e.invariant_fields == ["cited_policy_ids", "eligibility_decision"] for e in repeat_cells
    )
    assert all(e.samples == 10 and e.configs == 3 for e in plan.entries)
