"""Edges the main suites pass by: validation messages, chart preconditions, the lazy
engine, and the planted drift. Each one is a rule a user can hit, so each one is pinned."""
import json
import random

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient

from app import db
from app.config import settings
from app.engine.canonicalize import canonicalize, monotonic_violation_rate
from app.engine.charts import IndividualsChart, PChart
from app.engine.contracts import load_contract
from app.engine.embedding import HashingEmbedder
from app.engine.metamorphic import generate_paraphrases
from app.engine.sampler import Sample
from app.engine.suts import DriftSUT
from app.main import app

BASE = """
contract: edge
subject: s
invariants:
  - field: decision
    under: [repeat_run]
    relation: equal
run_policy: {samples: 4, configs: 1, confidence: 0.9}
gate: {max_decision_flip_rate: 0.1}
probes:
  - id: p1
    input: "One fact. A question?"
"""


@pytest.mark.parametrize("mutate,message", [
    (lambda t: t.replace("relation: equal", "relation: jaccard_at_least"), "requires a threshold"),
    (lambda t: t.replace("relation: equal", "relation: equal\n    threshold: 0.5"), "takes no threshold"),
    (lambda t: t.replace("relation: equal", "relation: jaccard_at_least\n    threshold: 1.5"), "must be in"),
    (lambda t: t.replace("id: p1", 'id: "  "'), "probe id must be non-empty"),
    (lambda t: t + '  - id: p1\n    input: "Again. Twice?"\n', "probe ids must be unique"),
    (lambda t: t.split("probes:")[0], "at least one probe or a golden set"),
    (lambda t: "- just\n- a list\n", "must be a mapping"),
    (lambda t: t + "sut: {adapter: jev, model: jev-1.13}\n", "must declare questions"),
])
def test_contract_validation_names_the_rule_that_was_broken(mutate, message):
    with pytest.raises(ValueError, match=message):
        load_contract(mutate(BASE))


GOLDEN = BASE.split("probes:")[0] + """sut: {adapter: jev, model: jev-1.13}
questions:
  q1: {type: noul, criteria_from: options.json}
golden: {path: golden.jsonl, kind: KIND}
"""


def _golden_dir(tmp_path, rows, kind="noul_flag", options=True):
    (tmp_path / "golden.jsonl").write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    if options:
        (tmp_path / "options.json").write_text(json.dumps(["a", "b"]), encoding="utf-8")
    return GOLDEN.replace("KIND", kind)


def test_a_golden_contract_turns_rows_into_probes_and_inlines_its_criteria(tmp_path):
    text = _golden_dir(tmp_path, [{"id": "g1", "label": "violation", "text": "some text"}])
    contract = load_contract(text, base_dir=tmp_path)
    assert [p.id for p in contract.probes] == ["g1"]
    assert contract.probes[0].expected == {"label": "violation"}
    assert contract.questions["q1"]["criteria"] == ["a", "b"]
    choice = _golden_dir(tmp_path, [{"id": "c1", "prompt": "route me", "expected": "x"}], "choice_top1")
    assert load_contract(choice, base_dir=tmp_path).probes[0].expected == {"choice": "x"}


@pytest.mark.parametrize("rows,kind,options,message", [
    ([{"label": "v", "text": "t"}], "noul_flag", True, "row 0 has no id"),
    ([{"id": "g1", "text": "t"}], "noul_flag", True, "needs label and text"),
    ([{"id": "c1", "prompt": "p"}], "choice_top1", True, "needs prompt and expected"),
    ([{"id": "g1", "label": "v", "text": "t"}], "noul_flag", False, "criteria_from file missing"),
    ([{"id": "g1", "label": "v", "text": "t"}], "something_else", True, "unknown golden kind"),
])
def test_a_golden_set_that_cannot_be_scored_is_refused(tmp_path, rows, kind, options, message):
    with pytest.raises(ValueError, match=message):
        load_contract(_golden_dir(tmp_path, rows, kind, options), base_dir=tmp_path)


def test_a_golden_contract_needs_its_directory_its_file_and_at_least_one_row(tmp_path):
    text = GOLDEN.replace("KIND", "noul_flag")
    with pytest.raises(ValueError, match="needs base_dir"):
        load_contract(text)
    with pytest.raises(ValueError, match="golden set missing"):
        load_contract(text, base_dir=tmp_path)
    (tmp_path / "golden.jsonl").write_text("\n", encoding="utf-8")
    with pytest.raises(ValueError, match="0 labeled rows"):
        load_contract(text, base_dir=tmp_path)


def test_charts_refuse_a_baseline_they_cannot_set_limits_from():
    with pytest.raises(ValueError, match="at least 8 points"):
        IndividualsChart([0.1] * 7)
    with pytest.raises(ValueError, match="at least 8 points"):
        PChart([0.1] * 7, n=20)
    with pytest.raises(ValueError, match="n >= 2"):
        PChart([0.1] * 8, n=1)


def test_the_run_of_eight_rule_signals_once_when_the_run_completes():
    chart = IndividualsChart([0.10, 0.12] * 4)
    points = [chart.add(i, 0.115) for i in range(10)]     # above the 0.11 mean, inside the limits
    assert [p.rule for p in points] == [None] * 7 + ["run8", None, None]
    on_center = chart.add(10, chart.center)
    assert on_center.alarm is False


def test_planted_drift_ramps_from_the_background_rate_to_its_peak():
    sut = DriftSUT(onset=5, peak_flip_rate=1.0, ramp=4, base_flip_p=0.0)
    flips = lambda t: sum(  # noqa: E731
        json.loads(sut.run("x", t, random.Random(i)))["eligibility_decision"] == "ineligible"
        for i in range(200))
    assert flips(4) == 0
    assert 0 < flips(5) < flips(7) < flips(8) == 200


def _s(parsed):
    return Sample("p", "repeat_run", "in", "raw", parsed)


def test_a_single_sample_has_no_pairs_and_reads_as_full_overlap():
    metrics = canonicalize([_s({"ids": ["a"]})], [], ["ids"], "", HashingEmbedder())
    assert metrics.jaccard_mean == {"ids": 1.0}
    with pytest.raises(ValueError, match="empty sample set"):
        canonicalize([], [], [], "", HashingEmbedder())


def test_a_rung_with_no_parseable_output_cannot_be_placed():
    rungs = [[_s({"d": "a"})], [_s(None)], [_s({"d": "b"})]]
    assert monotonic_violation_rate(rungs, "d", ["a", "b"]) == 1.0


class _NoCandidates:
    def complete(self, *, model, messages, json_schema):
        return {"paraphrases": []}


def test_a_model_that_proposes_nothing_yields_no_variants_and_no_model_is_refused():
    assert generate_paraphrases(_NoCandidates(), "m", "seed text", 3, HashingEmbedder()) == []
    with pytest.raises(RuntimeError, match="Refusing to guess a model"):
        generate_paraphrases(_NoCandidates(), "", "seed text", 3, HashingEmbedder())


def test_the_engine_is_created_lazily_from_the_configured_url(monkeypatch):
    monkeypatch.setattr(settings, "database_url", "sqlite://")
    monkeypatch.setattr(db, "_engine", None)
    monkeypatch.setattr(db, "_Session", None)
    engine = db.get_engine()
    assert engine.dialect.name == "sqlite" and db.get_engine() is engine
    with db.get_session() as session:
        assert session.execute(sa.text("select 1")).scalar() == 1


@pytest.fixture()
def client():
    engine = sa.create_engine("sqlite://", poolclass=sa.pool.StaticPool,
                              connect_args={"check_same_thread": False})
    db.metadata.create_all(engine)
    db.set_engine_for_tests(engine)
    return TestClient(app)


FULL = BASE.replace("contract: edge", "contract: edge-api").replace(
    "field: decision", "field: eligibility_decision")


def test_an_unknown_simulator_is_a_422_naming_it(client):
    assert client.post("/api/v1/contracts", json={"yaml": FULL}).status_code == 201
    r = client.post("/api/v1/runs", json={"contract": "edge-api", "sut": "nope"})
    assert r.status_code == 422 and r.json()["detail"] == "unknown sut 'nope'"


def test_the_real_embedder_without_a_key_is_a_503_with_the_reason_not_a_500(client, monkeypatch):
    monkeypatch.setattr(settings, "openrouter_api_key", "")
    assert client.post("/api/v1/contracts", json={"yaml": FULL}).status_code == 201
    r = client.post("/api/v1/runs", json={"contract": "edge-api", "embedder": "openrouter"})
    assert r.status_code == 503 and "OPENROUTER_API_KEY is not set" in r.json()["detail"]
    assert client.get("/api/v1/reports/edge-api").json()["runs"] == 0, "nothing was stored"


def test_the_real_embedder_is_built_from_settings_when_configured(monkeypatch):
    from app import routes

    monkeypatch.setattr(settings, "openrouter_api_key", "test-key")
    monkeypatch.setattr(settings, "embedding_model", "test/embed")
    assert routes._embedder("openrouter").name == "openrouter"
    assert routes._embedder("hashing").name.startswith("hashing")


MONOTONIC = FULL.replace("contract: edge-api", "contract: edge-ladder").replace(
    "    under: [repeat_run]\n    relation: equal",
    "    under: [monotonic]\n    relation: monotonic\n    order: [eligible, ineligible]") + (
    '    ladder: ["Bought 5 days ago. Refund?", "Bought 60 days ago. Refund?"]\n')


def test_a_monotonic_only_run_stores_metrics_and_no_mode_rows(client):
    assert client.post("/api/v1/contracts", json={"yaml": MONOTONIC}).status_code == 201, MONOTONIC
    run = client.post("/api/v1/runs", json={"contract": "edge-ladder", "sut": "non-monotonic"})
    assert run.status_code == 201 and run.json()["gate"] == "pass"
    detail = client.get(f"/api/v1/runs/{run.json()['run_id']}").json()
    assert [m["perturbation"] for m in detail["matrix"]] == ["monotonic"]
    assert detail["modes"] == []
    assert client.get("/api/v1/overview").json()["cells_with_second_mode"] == 0


def test_the_second_mode_count_covers_latest_runs_only(client):
    """A contract whose LATEST run is clean reports zero, whatever its history held."""
    yaml = FULL.replace("contract: edge-api", "contract: edge-modes").replace(
        "samples: 4", "samples: 40").replace("max_decision_flip_rate: 0.1", "max_decision_flip_rate: 1.0")
    assert client.post("/api/v1/contracts", json={"yaml": yaml}).status_code == 201
    client.post("/api/v1/runs", json={"contract": "edge-modes", "sut": "jump", "t": 20, "seed": 1})
    assert client.get("/api/v1/overview").json()["cells_with_second_mode"] == 1
    client.post("/api/v1/runs", json={"contract": "edge-modes", "sut": "stable", "t": 21})
    assert client.get("/api/v1/overview").json()["cells_with_second_mode"] == 0


# --------------------------------------------------------------------------- #
# guards added with the type pass: each states a requirement where it is used
# --------------------------------------------------------------------------- #
def test_a_golden_spec_built_directly_still_rejects_an_unknown_kind():
    from app.engine.contracts import GoldenSpec

    with pytest.raises(ValueError, match="unknown golden kind"):
        GoldenSpec(path="g.jsonl", kind="mystery")


def test_the_executor_samples_text_probes_and_says_so_for_an_object_input():
    from app.engine.contracts import Contract, compile_plan
    from app.engine.execute import execute_plan
    from app.engine.suts import DEMO_SUTS

    contract = Contract.model_validate({
        "contract": "object-input", "subject": "s",
        "invariants": [{"field": "decision", "under": ["repeat_run"], "relation": "equal"}],
        "run_policy": {"samples": 2, "configs": 1, "confidence": 0.9},
        "gate": {"max_decision_flip_rate": 0.1},
        "probes": [{"id": "p1", "input": {"days": 12}}],
    })
    with pytest.raises(ValueError, match="probe 'p1' has an object input"):
        execute_plan(contract, compile_plan(contract).entries, DEMO_SUTS["stable"],
                     t=0, seed=1, embedder=HashingEmbedder())


def test_jev_scoring_names_the_contract_section_it_is_missing():
    from app import jev_runner as jr

    plain = load_contract(BASE)
    for accessor, message in ((jr._golden, "declares no golden set"), (jr._sut, "has no sut"),
                              (jr._questions, "declares no questions")):
        with pytest.raises(jr.RunError, match=message):
            accessor(plain)
    assert jr._declared(0.7, "confidence_cutoff") == 0.7


def test_cli_run_measures_every_cell_reports_the_unmeasured_and_refuses_zero_points(tmp_path, capsys):
    from app import cli

    path = tmp_path / "c.yaml"
    path.write_text(FULL.replace("under: [repeat_run]", "under: [repeat_run, format, paraphrase]"),
                    encoding="utf-8")
    assert cli.run(str(path), "format-sensitive", 2, 7, None) == 1, "the format cell is measured now"
    out = capsys.readouterr().out
    assert "**BLOCK**" in out
    assert "not measured: probe `p1` under paraphrase: no accepted paraphrase variants generated yet" in out
    assert cli.run(str(path), "stable", 0, 7, None) == 2
    assert "--points must be at least 1" in capsys.readouterr().err


# --------------------------------------------------------------------------- #
# review findings, 2026-11-09: each was reproduced before it was fixed
# --------------------------------------------------------------------------- #
TYPO = FULL.replace("contract: edge-api", "contract: edge-typo").replace(
    "field: eligibility_decision", "field: eligibilty_decison")


@pytest.mark.parametrize("sut", ["stable", "jump", "format-sensitive"])
def test_a_misspelt_invariant_field_blocks_every_system_instead_of_passing_them(client, sut):
    """The field is in no output, so None equalled None on every sample: flip 0.0, pass."""
    assert client.post("/api/v1/contracts", json={"yaml": TYPO}).status_code == 201
    run = client.post("/api/v1/runs", json={"contract": "edge-typo", "sut": sut, "t": 20}).json()
    assert run["gate"] == "block"
    assert run["worst_malformed_rate"] == 1.0 and run["worst_flip_rate"] == 1.0
    assert any("malformed rate 100.0%" in reason for reason in run["reasons"])


def test_tolerating_malformed_output_does_not_turn_an_unreadable_cell_into_a_pass(client):
    yaml = TYPO.replace("contract: edge-typo", "contract: edge-tolerant").replace(
        "max_decision_flip_rate: 0.1", "max_decision_flip_rate: 0.1, max_malformed_rate: 1.0")
    assert client.post("/api/v1/contracts", json={"yaml": yaml}).status_code == 201
    run = client.post("/api/v1/runs", json={"contract": "edge-tolerant"}).json()
    assert run["gate"] == "block" and "flip rate 100.0%" in run["reasons"][0]


TWO_THRESHOLDS = """
contract: edge-two-thresholds
subject: s
invariants:
  - field: cited_policy_ids
    under: [repeat_run]
    relation: jaccard_at_least
    threshold: 0.99
  - field: cited_policy_ids
    under: [format]
    relation: jaccard_at_least
    threshold: 0.1
run_policy: {samples: 40, configs: 1, confidence: 0.9}
gate: {max_decision_flip_rate: 1.0}
probes:
  - id: p1
    input: "Bought 12 days ago. Refund?"
"""


def test_each_cell_is_held_to_the_threshold_declared_for_its_own_perturbation(client):
    """A later invariant on the same field used to overwrite the earlier threshold."""
    from app.engine.execute import jaccard_threshold

    contract = load_contract(TWO_THRESHOLDS)
    assert jaccard_threshold(contract, "cited_policy_ids", "repeat_run") == 0.99
    assert jaccard_threshold(contract, "cited_policy_ids", "format") == 0.1
    assert jaccard_threshold(contract, "cited_policy_ids", "reordering") is None

    assert client.post("/api/v1/contracts", json={"yaml": TWO_THRESHOLDS}).status_code == 201
    run = client.post("/api/v1/runs", json={"contract": "edge-two-thresholds", "sut": "bimodal",
                                            "t": 20, "seed": 3}).json()
    failed = {(f["perturbation"], f["threshold"]) for f in run["jaccard_failures"]}
    assert failed == {("repeat_run", 0.99)}, run["jaccard_failures"]
    assert run["gate"] == "block"
    matrix = client.get(f"/api/v1/runs/{run['run_id']}").json()["matrix"]
    assert {m["perturbation"]: m["violated"] for m in matrix} == {"repeat_run": True, "format": False}


def test_one_miss_after_a_perfect_baseline_does_not_quarantine_a_judge():
    from app.engine.judges import quarantine

    perfect = [1.0] * 8
    for n in (20, 50, 200):
        assert quarantine(perfect + [(n - 1) / n], n) == (False, None), n
    assert quarantine(perfect + [0.90], n=20) == (True, "drift"), "two misses in twenty still signal"
    assert PChart(perfect, n=20).lcl == pytest.approx(1 - 1.5 / 20)
    assert PChart([0.02] * 8, n=20).lcl == 0.0, "a chart read from above keeps its zero floor"


def test_a_tie_between_two_reference_sets_resolves_the_same_way_in_every_process():
    import subprocess
    import sys

    code = (
        "from app.engine.canonicalize import _modal;"
        "print(sorted(_modal([frozenset('bc'), frozenset('ad')] * 3)))"
    )
    seen = {subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60,
                           env={**__import__('os').environ, "PYTHONHASHSEED": seed}).stdout.strip()
            for seed in ("1", "2", "3", "4", "5", "6")}
    assert seen == {"['a', 'd']"}, seen


def test_the_matrix_marks_the_cell_a_second_mode_gate_blocked(client):
    yaml = FULL.replace("contract: edge-api", "contract: edge-mode-gate").replace(
        "samples: 4", "samples: 40").replace(
        "max_decision_flip_rate: 0.1", "max_decision_flip_rate: 1.0, max_second_mode_share: 0.02")
    assert client.post("/api/v1/contracts", json={"yaml": yaml}).status_code == 201
    run = client.post("/api/v1/runs", json={"contract": "edge-mode-gate", "sut": "jump",
                                            "t": 20, "seed": 1}).json()
    assert run["gate"] == "block" and "second mode above 2.0%" in run["reasons"][0]
    for source in (client.get(f"/api/v1/runs/{run['run_id']}").json(),
                   client.get("/api/v1/reports/edge-mode-gate").json()):
        row = source["matrix"][0]
        assert row["violated"] is True and row["second_mode_share"] > 0.02


def test_sentences_that_all_read_the_same_are_refused_at_registration_not_mid_run(client):
    yaml = FULL.replace("contract: edge-api", "contract: edge-same").replace(
        "under: [repeat_run]", "under: [repeat_run, reordering]").replace(
        '"One fact. A question?"', '"Refund please? Refund please?"')
    r = client.post("/api/v1/contracts", json={"yaml": yaml})
    assert r.status_code == 422
    assert "probe 'p1': reordering needs sentences that differ" in r.json()["detail"]
    from app.engine.perturb import reorderings

    assert reorderings("A. B. A.", 4) == ["A. A. B.", "B. A. A.", "A. A. B.", "B. A. A."]
