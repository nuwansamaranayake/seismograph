"""app.jev_runner: planning, scoring, persistence, calibration and drift.

No network. The live target is replaced by a scripted fake that returns
JevCallRecord objects, so every number asserted here comes from known inputs.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app import jev_runner as jr
from app.engine.contracts import load_contract
from app.jev import JevAnswer, JevCallRecord
from app.jev_runner import RunError

NOUL_YAML = """
contract: noul-c
subject: t
sut: {{adapter: jev, model: jev-1.13, timeout_seconds: 7}}
golden:
  path: golden.jsonl
  kind: noul_flag
  positive_label: violation
  min_rows: {min_rows}
  {flag_line}
  type_to_question: {{remedy: remedy_q}}
questions:
  remedy_q: {{type: noul, instructions: "Remedy?"}}
  other_q: {{type: noul, instructions: "Other?"}}
invariants:
  - {{field: flagged, under: [repeat_run], relation: equal}}
run_policy: {{samples: 2, configs: 1, confidence: 0.95}}
gate: {{confidence_cutoff: 0.7, min_recall: 0.9, max_false_positive_rate: 0.3, max_decision_flip_rate: 0.6}}
"""

CHOICE_YAML = """
contract: choice-c
subject: t
sut: {adapter: jev, model: jev-1.13}
golden:
  path: golden.jsonl
  kind: choice_top1
questions:
  skill: {type: choice, instructions: "Which?", criteria: {a: A, b: B}}
invariants:
  - {field: skill, under: [repeat_run], relation: equal}
run_policy: {samples: 2, configs: 1, confidence: 0.95}
gate: {max_decision_flip_rate: 0.6, min_top1_accuracy: 0.6}
"""

NOUL_ROWS = [
    {"id": "v1", "label": "violation", "violation_type": "remedy", "text": "a", "engine_level": "DIRECT"},
    {"id": "v2", "label": "violation", "violation_type": "mystery", "text": "b", "engine_level": "NONE"},
    {"id": "c1", "label": "clean", "violation_type": None, "text": "c", "engine_level": "LIKELY"},
    {"id": "c2", "label": "clean", "violation_type": None, "text": "d", "engine_level": "NONE"},
]


def _write(tmp_path, rows):
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "golden.jsonl").write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")


def noul_contract(tmp_path, rows=None, *, flag=None, min_rows=1):
    _write(tmp_path, rows or NOUL_ROWS)
    flag_line = f"flag_question: {flag}" if flag else ""
    return load_contract(NOUL_YAML.format(min_rows=min_rows, flag_line=flag_line), base_dir=tmp_path)


def choice_contract(tmp_path, rows=None):
    _write(tmp_path, rows or [
        {"id": "p1", "prompt": "x", "expected": "a"},
        {"id": "p2", "prompt": "y", "expected": "b"},
    ])
    return load_contract(CHOICE_YAML, base_dir=tmp_path)


def noul(qid, p):
    return JevAnswer(qid, "noul", p, {"true": p, "false": 1 - p}, max(p, 1 - p))


def choice(qid, pick, probs):
    return JevAnswer(qid, "choice", pick, probs, max(probs.values()))


def rec(probe, run, answers, *, model="typesafe/jev-1.13", latency=10, cost=1e-5, tokens=100):
    return JevCallRecord(
        target_id="jev:x", adapter="jev", route="/v1/systemone", arguments_hash="h",
        latency_ms=latency, model=model, probe_id=probe, run_index=run, answers=answers,
        input_tokens=tokens, output_tokens=5, usage_cost=cost,
        created_at=datetime(2026, 1, 1, tzinfo=UTC))


def both(p_remedy, p_other=0.0):
    return {"remedy_q": noul("remedy_q", p_remedy), "other_q": noul("other_q", p_other)}


# ------------------------------------------------------- resolve / guards ---
def test_resolve_contract_by_path_name_and_missing(tmp_path):
    c = noul_contract(tmp_path)
    cdir = tmp_path / "contracts"
    cdir.mkdir()
    text = NOUL_YAML.format(min_rows=1, flag_line="")
    (cdir / "named.yaml").write_text(text, encoding="utf-8")
    (cdir / "golden.jsonl").write_text(
        "\n".join(json.dumps(r) for r in NOUL_ROWS), encoding="utf-8")
    loaded, path = jr.resolve_contract(str(cdir / "named.yaml"))
    assert loaded.contract == "noul-c" and path == cdir / "named.yaml"
    loaded, path = jr.resolve_contract("named", contracts_dir=str(cdir))
    assert path == cdir / "named.yaml" and len(loaded.probes) == len(c.probes)
    with pytest.raises(RunError, match="contract not found: 'ghost'"):
        jr.resolve_contract("ghost", contracts_dir=str(cdir))


def test_is_jev_contract_and_require_guards(tmp_path):
    c = noul_contract(tmp_path)
    assert jr.is_jev_contract(c)
    jr._require_jev(c)
    no_sut = c.model_copy(update={"sut": None})
    assert not jr.is_jev_contract(no_sut)
    with pytest.raises(RunError, match="has no jev sut"):
        jr._require_jev(no_sut)
    other = c.model_copy(update={"sut": c.sut.model_copy(update={"adapter": "http"})})
    assert not jr.is_jev_contract(other)
    with pytest.raises(RunError, match="declares no questions"):
        jr._require_jev(c.model_copy(update={"questions": {}}))
    with pytest.raises(RunError, match="declares no golden set"):
        jr._require_jev(c.model_copy(update={"golden": None}))
    small = c.model_copy(update={"golden": c.golden.model_copy(update={"min_rows": 99})})
    with pytest.raises(RunError, match="4 labeled rows; contract requires at least 99"):
        jr._require_jev(small)


def test_estimate_cost_scales_with_samples(tmp_path):
    c = noul_contract(tmp_path)
    calls2, cost2 = jr.estimate_cost_usd(c, 2)
    calls4, cost4 = jr.estimate_cost_usd(c, 4)
    assert (calls2, calls4) == (8, 16)
    assert cost2 > 0 and cost4 == pytest.approx(2 * cost2)


def test_percentile():
    assert jr._percentile([], 0.5) != jr._percentile([], 0.5)  # nan
    assert jr._percentile([7], 0.95) == 7.0
    assert jr._percentile([1, 2, 3], 0.5) == 2.0
    assert jr._percentile([10, 0], 0.5) == 5.0
    assert jr._percentile([0, 10, 20, 30], 0.95) == pytest.approx(28.5)


# ----------------------------------------------------------------- execute ---
class FakeTarget:
    def __init__(self, fn=None, model="typesafe/jev-1.13"):
        self.fn = fn or (lambda state, probe_id, run_index: both(0.9))
        self.model = model
        self.calls = []
        self.closed = False

    def call(self, state, questions, *, probe_id="", run_index=0):
        self.calls.append((state, probe_id, run_index, questions))
        return rec(probe_id, run_index, self.fn(state, probe_id, run_index), model=self.model)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.closed = True


def test_execute_runs_every_cell_sorted(tmp_path, capsys):
    c = noul_contract(tmp_path)
    target = FakeTarget()
    records = jr.execute(c, target, workers=3)
    assert [(r.probe_id, r.run_index) for r in records] == sorted(
        (p, i) for p in ("c1", "c2", "v1", "v2") for i in range(2))
    assert {call[0] for call in target.calls} == {"a", "b", "c", "d"}
    assert all(call[3] == c.questions for call in target.calls)
    out = capsys.readouterr().out
    assert "4 probes x 2 runs = 8 live calls" in out


def test_execute_samples_override(tmp_path):
    c = noul_contract(tmp_path)
    assert len(jr.execute(c, FakeTarget(), samples=3, workers=2)) == 12


def test_execute_budget_stops_before_any_call(tmp_path):
    c = noul_contract(tmp_path)
    target = FakeTarget()
    with pytest.raises(RunError, match="exceeds budget 0.00; stopping before any call"):
        jr.execute(c, target, budget_usd=0.0)
    assert target.calls == []


def test_execute_zero_cells(tmp_path):
    c = noul_contract(tmp_path).model_copy(update={"invariants": []})
    with pytest.raises(RunError, match="zero repeat_run cells"):
        jr.execute(c, FakeTarget())


def test_execute_first_failure_aborts_with_probe_named(tmp_path):
    c = noul_contract(tmp_path)

    def boom(state, probe_id, run_index):
        if probe_id == "c1":
            raise ValueError("kaput")
        return both(0.9)

    with pytest.raises(RunError, match="live call failed for probe c1 run [01]: kaput") as ei:
        jr.execute(c, FakeTarget(boom), workers=1)
    assert isinstance(ei.value.__cause__, ValueError)


# ------------------------------------------------------------ flag helpers ---
def test_flag_decision_and_prob():
    r = rec("p", 0, both(0.8, 0.3))
    assert jr._flag_decision(r, 0.7, "remedy_q") is True
    assert jr._flag_decision(r, 0.9, "remedy_q") is False
    assert jr._flag_decision(r, 0.7) is True          # any noul at/above cutoff
    assert jr._flag_decision(r, 0.95) is False
    assert jr._flag_prob(r, "other_q") == 0.3
    assert jr._flag_prob(r, None) == 0.8              # max over nouls
    mixed = rec("p", 0, {"c": choice("c", "a", {"a": 1.0}), "n": noul("n", 0.4)})
    assert jr._flag_decision(mixed, 0.1) is True and jr._flag_prob(mixed, None) == 0.4


def test_flip_rates():
    assert jr._flip_rates({}) == (0.0, 0.0)
    assert jr._flip_rates({"a": []}) == (0.0, 0.0)
    mean, worst = jr._flip_rates({"a": [True, True, False, True], "b": [True, True], "c": []})
    assert worst == pytest.approx(0.25) and mean == pytest.approx(0.125)


# ------------------------------------------------------------ cutoff sweep ---
def test_cutoff_sweep_picks_highest_cutoff_reaching_recall(tmp_path):
    c = noul_contract(tmp_path, flag="remedy_q")
    records = [
        rec("v1", 0, both(0.92)), rec("v2", 0, both(0.62)),
        rec("c1", 0, both(0.55)), rec("c2", 0, both(0.1)),
    ]
    sweep = jr.cutoff_sweep(c, records, target_recall=1.0, step=0.1)
    assert sweep["positives"] == 2 and sweep["negatives"] == 2
    assert [row["cutoff"] for row in sweep["table"]] == [round(i * 0.1, 2) for i in range(1, 10)]
    assert sweep["cutoff_for_target_recall"] == {
        "cutoff": 0.6, "recall": 1.0, "false_positive_rate": 0.0}
    at_half = next(r for r in sweep["table"] if r["cutoff"] == 0.5)
    assert at_half["false_positive_rate"] == 0.5


def test_cutoff_sweep_without_positives_or_negatives(tmp_path):
    c = noul_contract(tmp_path, rows=[
        {"id": "c1", "label": "clean", "violation_type": None, "text": "c"}])
    sweep = jr.cutoff_sweep(c, [rec("c1", 0, both(0.5))])
    assert sweep["cutoff_for_target_recall"] is None and sweep["positives"] == 0
    assert sweep["table"][0]["recall"] != sweep["table"][0]["recall"]  # nan
    c2 = noul_contract(tmp_path, rows=[
        {"id": "v1", "label": "violation", "violation_type": "remedy", "text": "a"}])
    sweep = jr.cutoff_sweep(c2, [rec("v1", 0, both(0.99))])
    assert sweep["table"][0]["false_positive_rate"] != sweep["table"][0]["false_positive_rate"]
    assert sweep["cutoff_for_target_recall"]["cutoff"] == 0.95


# ------------------------------------------------------ engine disagreement ---
def test_engine_disagreements_buckets(tmp_path):
    rows = NOUL_ROWS + [
        {"id": "v3", "label": "violation", "violation_type": "remedy", "text": "e", "engine_level": "NONE"},
        {"id": "c3", "label": "clean", "violation_type": None, "text": "f", "engine_level": "DIRECT"},
        {"id": "x1", "label": "clean", "violation_type": None, "text": "g"},   # no engine tier
    ]
    c = noul_contract(tmp_path, rows=rows, flag="remedy_q")
    records = []
    hi, lo = both(0.9), both(0.1)
    for pid, ans in (("v1", hi), ("v2", lo), ("c1", lo), ("c2", lo),
                     ("v3", hi), ("c3", lo), ("x1", lo)):
        records += [rec(pid, 0, ans), rec(pid, 1, ans)]
    out = jr.engine_disagreements(c, records, cutoff=0.7)
    # v1: jev flag, engine DIRECT, human violation -> both right
    # v2: jev no, engine NONE, human violation -> both wrong
    # c1: jev no, engine LIKELY, human clean -> disagree, jev right
    # c2: jev no, engine NONE, human clean -> both right
    # v3: jev flag, engine NONE, human violation -> disagree, jev right
    # c3: jev no, engine DIRECT, human clean -> disagree, jev right
    assert out["pairs_with_engine_tier"] == 6
    assert out["agree_both_right"] == 2 and out["agree_both_wrong"] == 1
    assert out["disagree_jev_right"] == 3 and out["disagree_engine_right"] == 0
    assert sorted(out["disagree_jev_right_ids"]) == ["c1", "c3", "v3"]


def test_engine_disagreements_engine_right(tmp_path):
    rows = [{"id": "c1", "label": "clean", "violation_type": None, "text": "c", "engine_level": "NONE"}]
    c = noul_contract(tmp_path, rows=rows, flag="remedy_q")
    out = jr.engine_disagreements(c, [rec("c1", 0, both(0.99))], cutoff=0.7)
    assert out["disagree_engine_right"] == 1 and out["disagree_engine_right_ids"] == ["c1"]


# ---------------------------------------------------------------- summarize ---
def test_summarize_noul_flag_passes_and_reports(tmp_path):
    c = noul_contract(tmp_path, flag="remedy_q")
    records = []
    for pid, p in (("v1", 0.9), ("v2", 0.85), ("c1", 0.1), ("c2", 0.0)):
        records += [rec(pid, 0, both(p), latency=10, cost=1e-5),
                    rec(pid, 1, both(p), latency=30, cost=2e-5)]
    s = jr.summarize(c, records)
    m = s["metrics"]
    assert s["passed"] is True and s["kind"] == "noul_flag"
    assert (m["tp"], m["fn"], m["fp"], m["tn"]) == (4, 0, 0, 4)
    assert m["recall"] == 1.0 and m["false_positive_rate"] == 0.0
    # 'mystery' has no mapped question -> falls back to the flag decision
    assert m["recall_by_type_matching_question"] == {"remedy": 1.0, "mystery": 1.0}
    assert s["usage"]["input_tokens"] == 800
    assert s["usage"]["cost_usd"] == pytest.approx(12e-5)
    assert s["latency_ms"] == {"p50": 20.0, "p95": 30.0}
    assert s["model"] == "typesafe/jev-1.13" and s["records"] == 8
    assert s["gate"]["min_recall"] == 0.9
    json.dumps(s, default=str)  # serialisable


def test_summarize_noul_flag_fails_on_fpr_and_flip(tmp_path):
    c = noul_contract(tmp_path, flag="remedy_q")
    records = [
        rec("v1", 0, both(0.9)), rec("v1", 1, both(0.9)),
        rec("v2", 0, both(0.9)), rec("v2", 1, both(0.9)),
        rec("c1", 0, both(0.9)), rec("c1", 1, both(0.1)),   # flips, one FP
        rec("c2", 0, both(0.9)), rec("c2", 1, both(0.9)),   # two FP
    ]
    s = jr.summarize(c, records)
    assert s["passed"] is False
    assert s["metrics"]["false_positive_rate"] == pytest.approx(0.75)
    assert s["metrics"]["flip_rate_worst"] == pytest.approx(0.5)


def test_summarize_noul_flag_uses_type_question_when_mapped(tmp_path):
    c = noul_contract(tmp_path, flag="other_q")
    # flag question says yes, but the type-matching question (remedy_q) says no
    records = [rec("v1", 0, both(0.1, 0.9)), rec("v2", 0, both(0.1, 0.9))]
    s = jr.summarize(c, records)
    assert s["metrics"]["tp"] == 2
    assert s["metrics"]["recall_by_type_matching_question"]["remedy"] == 0.0
    assert s["metrics"]["recall_by_type_matching_question"]["mystery"] == 1.0
    assert s["metrics"]["recall"] == 1.0
    assert s["metrics"]["false_positive_rate"] != s["metrics"]["false_positive_rate"]  # nan


def test_summarize_requires_cutoff(tmp_path):
    c = noul_contract(tmp_path)
    c = c.model_copy(update={"gate": c.gate.model_copy(update={"confidence_cutoff": None})})
    with pytest.raises(RunError, match="needs gate.confidence_cutoff"):
        jr.summarize(c, [rec("v1", 0, both(0.9))])


def test_summarize_unknown_kind(tmp_path):
    c = noul_contract(tmp_path)
    c = c.model_copy(update={"golden": c.golden.model_copy(update={"kind": "other"})})
    with pytest.raises(RunError, match="unknown golden kind 'other'"):
        jr.summarize(c, [])


def test_summarize_choice_top1(tmp_path):
    c = choice_contract(tmp_path)
    ans = lambda pick: {"skill": choice("skill", pick, {"a": 0.5, "b": 0.5})}  # noqa: E731
    records = [rec("p1", 0, ans("a")), rec("p1", 1, ans("a")),
               rec("p2", 0, ans("b")), rec("p2", 1, ans("a"))]
    s = jr.summarize(c, records)
    m = s["metrics"]
    assert m["top1_accuracy"] == 0.75 and m["correct"] == 3
    assert m["confusions_expected_to_chosen"] == {"b": {"a": 1}}
    assert m["flip_rate_worst"] == 0.5
    assert s["passed"] is True
    bad = [rec("p1", 0, ans("b")), rec("p2", 0, ans("a"))]
    assert jr.summarize(c, bad)["passed"] is False
    empty = jr.summarize(c, [])
    assert empty["model"] is None and empty["metrics"]["top1_accuracy"] != empty["metrics"]["top1_accuracy"]
    assert empty["passed"] is False


# ------------------------------------------------------------- persistence ---
def test_write_and_latest_records(tmp_path):
    c = noul_contract(tmp_path / "g")
    reports = str(tmp_path / "reports")
    assert jr.latest_records(c, reports) is None            # no runs dir yet
    records = [rec(p, i, both(0.5)) for p in ("v1", "v2", "c1", "c2") for i in range(2)]
    path = jr.write_records(c, records, reports)
    assert path.parent == tmp_path / "reports" / "noul-c" / "runs" and path.suffix == ".jsonl"
    tagged = jr.write_records(c, records[:2], reports, tag="drift-x")
    assert tagged.name.endswith("-drift-x.jsonl")
    assert path.read_text(encoding="utf-8").count("\n") == 8
    got = jr.latest_records(c, reports)
    # the newer tagged file holds 2 probes only, so it is skipped for the complete set
    assert got is not None and len(got) == 8
    only_full = jr.latest_records(c, reports, model="jev-1.13")
    assert {r.probe_id for r in only_full} == {"v1", "v2", "c1", "c2"}


def test_latest_records_skips_empty_other_models_and_partial_sets(tmp_path):
    c = noul_contract(tmp_path / "g")
    reports = tmp_path / "reports"
    runs = reports / "noul-c" / "runs"
    runs.mkdir(parents=True)
    full = [rec(p, 0, both(0.5), model="typesafe/other-9") for p in ("v1", "v2", "c1", "c2")]
    (runs / "20260101T000000Z.jsonl").write_text(
        "\n".join(json.dumps(r.to_json()) for r in full), encoding="utf-8")
    (runs / "20260102T000000Z.jsonl").write_text("\n\n", encoding="utf-8")          # blank
    partial = [rec("v1", 0, both(0.5))]
    (runs / "20260103T000000Z.jsonl").write_text(
        json.dumps(partial[0].to_json()), encoding="utf-8")                         # missing ids
    assert jr.latest_records(c, str(reports), model="jev-1.13") is None             # wrong model
    got = jr.latest_records(c, str(reports))                                        # any model
    assert got is not None and len(got) == 4


# -------------------------------------------------------------- run_contract ---
class FakeJevTargetClass:
    """Stands in for app.jev.JevTarget inside app.jev_runner."""

    built: list = []

    def __init__(self, model, timeout):
        self.model = model
        self.timeout = timeout

    @classmethod
    def from_env(cls, model, *, timeout=30.0, transport=None, target_id=None):
        t = cls(model, timeout)
        cls.built.append(t)
        return t

    def call(self, state, questions, *, probe_id="", run_index=0):
        p = 0.9 if probe_id.startswith("v") else 0.1
        return rec(probe_id, run_index, both(p, 0.0), model=f"typesafe/{self.model}")

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return None


@pytest.fixture
def fake_jev(monkeypatch):
    FakeJevTargetClass.built = []
    monkeypatch.setattr(jr, "JevTarget", FakeJevTargetClass)
    monkeypatch.setattr(jr, "hydrate_env_from_user_scope", lambda: [])
    return FakeJevTargetClass


def test_run_contract_writes_records_and_run_json(tmp_path, fake_jev):
    c = noul_contract(tmp_path / "g", flag="remedy_q")
    reports = str(tmp_path / "reports")
    summary = jr.run_contract(c, workers=2, reports_dir=reports)
    assert fake_jev.built[0].model == "jev-1.13" and fake_jev.built[0].timeout == 7
    run_json = json.loads((tmp_path / "reports" / "noul-c" / "run.json").read_text(encoding="utf-8"))
    assert run_json["records_path"] == summary["records_path"]
    assert run_json["passed"] is True and "run_at" in run_json
    assert len(Path(summary["records_path"]).read_text(encoding="utf-8").splitlines()) == 8


def test_run_contract_model_override(tmp_path, fake_jev):
    c = noul_contract(tmp_path / "g", flag="remedy_q")
    jr.run_contract(c, model="jev-2", reports_dir=str(tmp_path / "r"))
    assert fake_jev.built[0].model == "jev-2"


def test_run_contract_requires_jev_contract(tmp_path, fake_jev):
    c = noul_contract(tmp_path / "g").model_copy(update={"sut": None})
    with pytest.raises(RunError):
        jr.run_contract(c, reports_dir=str(tmp_path / "r"))
    assert fake_jev.built == []


# --------------------------------------------------------------- calibration ---
def test_calibration_points_flag_question_mode(tmp_path):
    c = noul_contract(tmp_path, flag="remedy_q")
    r = rec("v1", 0, both(0.8, 0.9))      # truth: violation; other_q ignored
    assert jr.calibration_points(c, [r]) == [(0.8, True)]
    r2 = rec("c1", 0, both(0.3, 0.9))      # clean; p<0.5 -> predicts clean -> correct, conf 0.7
    (conf, ok), = jr.calibration_points(c, [r2])
    assert conf == pytest.approx(0.7) and ok is True


def test_calibration_points_type_mapped_mode(tmp_path):
    c = noul_contract(tmp_path)    # no flag_question
    # v1 is type 'remedy' -> only remedy_q is true; other_q truth is False
    pts = jr.calibration_points(c, [rec("v1", 0, both(0.9, 0.9))])
    assert pts == [(0.9, True), (0.9, False)]
    # v2 has an unmapped type -> truth False for every question
    pts = jr.calibration_points(c, [rec("v2", 0, both(0.2, 0.2))])
    assert all(ok for _, ok in pts) and len(pts) == 2


def test_calibration_points_choice_and_skips(tmp_path):
    c = choice_contract(tmp_path)
    nouls = {"n": noul("n", 0.9), "skill": choice("skill", "a", {"a": 0.8, "b": 0.2})}
    pts = jr.calibration_points(c, [rec("p1", 0, nouls), rec("p2", 0, nouls)])
    # nouls skipped for choice_top1; choice a correct for p1, wrong for p2
    assert pts == [(0.8, True), (0.8, False)]
    c2 = noul_contract(tmp_path / "n", flag="remedy_q")
    only_choice = {"c": choice("c", "a", {"a": 0.8, "b": 0.2})}
    assert jr.calibration_points(c2, [rec("v1", 0, only_choice)]) == []  # no 'choice' truth


def test_calibrate_from_records_bins_and_ece(tmp_path):
    c = noul_contract(tmp_path / "g", flag="remedy_q")
    records = [
        rec("v1", 0, both(1.0)),       # conf 1.0 correct (top bin includes exactly 1.0)
        rec("v2", 0, both(0.65)),      # conf 0.65 correct
        rec("c1", 0, both(0.85)),      # conf 0.85, predicts violation but clean -> wrong
        rec("c2", 0, both(0.0)),       # conf 1.0 correct
    ]
    out = jr.calibrate(c, records=records, reports_dir=str(tmp_path / "r"))
    bins = {b["bin"]: b for b in out["bins"]}
    assert out["points"] == 4 and out["source"] == "existing run records"
    assert bins["0.9-1.0"]["count"] == 2 and bins["0.9-1.0"]["accuracy"] == 1.0
    assert bins["0.6-0.7"]["count"] == 1 and bins["0.8-0.9"]["accuracy"] == 0.0
    assert bins["0.5-0.6"]["count"] == 0 and bins["0.5-0.6"]["abs_gap"] is None
    expected_ece = 0.25 * abs(1 - 0.65) + 0.25 * abs(0 - 0.85) + 0.5 * abs(1 - 1.0)
    assert out["expected_calibration_error"] == pytest.approx(expected_ece)
    assert out["cutoff_sweep"]["positives"] == 2
    saved = json.loads((tmp_path / "r" / "noul-c" / "calibration.json").read_text(encoding="utf-8"))
    assert saved["points"] == 4


def test_calibrate_choice_contract_has_no_sweep(tmp_path):
    c = choice_contract(tmp_path / "g")
    records = [rec("p1", 0, {"skill": choice("skill", "a", {"a": 0.9, "b": 0.1})}),
               rec("p2", 0, {"skill": choice("skill", "b", {"a": 0.1, "b": 0.9})})]
    out = jr.calibrate(c, records=records, reports_dir=str(tmp_path / "r"))
    assert "cutoff_sweep" not in out and out["expected_calibration_error"] == pytest.approx(0.1)


def test_calibrate_no_points_raises(tmp_path):
    c = noul_contract(tmp_path / "g", flag="remedy_q")
    with pytest.raises(RunError, match="no calibration points"):
        jr.calibrate(c, records=[rec("v1", 0, {})], reports_dir=str(tmp_path / "r"))


def test_calibrate_runs_live_when_no_records(tmp_path, fake_jev):
    c = noul_contract(tmp_path / "g", flag="remedy_q")
    out = jr.calibrate(c, reports_dir=str(tmp_path / "r"), workers=2)
    assert out["source"] == "fresh live run" and out["records"] == 8
    assert fake_jev.built  # a live target was constructed


def test_calibrate_live_run_that_stores_nothing_raises(tmp_path, monkeypatch):
    c = noul_contract(tmp_path / "g", flag="remedy_q")
    monkeypatch.setattr(jr, "run_contract", lambda *a, **k: {})
    with pytest.raises(RunError, match="no records after a live run"):
        jr.calibrate(c, reports_dir=str(tmp_path / "r"))


# --------------------------------------------------------------------- drift ---
def test_decisions_default_cutoff_when_unset(tmp_path):
    c = noul_contract(tmp_path)
    r = rec("v1", 0, {"remedy_q": noul("remedy_q", 0.75), "c": choice("c", "a", {"a": 1.0})})
    assert jr._decisions(c, r) == {"remedy_q": True, "c": "a"}      # cutoff 0.7
    c2 = c.model_copy(update={"gate": c.gate.model_copy(update={"confidence_cutoff": None})})
    assert jr._decisions(c2, rec("v1", 0, {"q": noul("q", 0.5)})) == {"q": True}
    assert jr._decisions(c2, rec("v1", 0, {"q": noul("q", 0.49)})) == {"q": False}


class DriftTarget(FakeJevTargetClass):
    """Model 'jev-a' says yes, model 'jev-b' flips the answer for probes in FLIP."""

    FLIP: set = set()

    def call(self, state, questions, *, probe_id="", run_index=0):
        p = 0.9
        if self.model == "jev-b" and probe_id in self.FLIP:
            p = 0.1
        return rec(probe_id, run_index, both(p, 0.5), model=f"typesafe/{self.model}",
                   cost=1e-5, latency=5 + run_index)


def _many_rows(n):
    return [{"id": f"p{i:03d}", "label": "violation", "violation_type": "remedy", "text": f"t{i}"}
            for i in range(n)]


def test_drift_small_set_has_no_control_chart(tmp_path, monkeypatch):
    DriftTarget.built = []
    DriftTarget.FLIP = {"v1"}
    monkeypatch.setattr(jr, "JevTarget", DriftTarget)
    monkeypatch.setattr(jr, "hydrate_env_from_user_scope", lambda: [])
    c = noul_contract(tmp_path / "g", flag="remedy_q")
    out = jr.drift(c, "jev-a", "jev-b", reports_dir=str(tmp_path / "r"), workers=2)
    assert out["pairs"] == 8 and out["model_a_served"] == "typesafe/jev-a"
    # remedy_q: 2 of 8 pairs (v1 x2) disagree; other_q never differs
    assert out["per_question"]["remedy_q"]["agreement_rate"] == pytest.approx(0.75)
    assert out["per_question"]["other_q"]["agreement_rate"] == 1.0
    assert out["per_question"]["remedy_q"]["mean_total_variation"] == pytest.approx(0.8 * 2 / 8)
    assert out["overall_agreement"] == pytest.approx(0.875)
    chart = out["control_chart"]
    assert chart["series"] == [pytest.approx(0.25)] and chart["points"] == []
    assert "needs 9+ batches; have 1" in chart["note"]
    assert set(out["usage"]) == {"jev-a", "jev-b"}
    assert out["usage"]["jev-a"]["cost_usd"] == pytest.approx(8e-5)
    assert (tmp_path / "r" / "noul-c" / "drift.json").exists()
    runs = sorted(p.name for p in (tmp_path / "r" / "noul-c" / "runs").glob("*.jsonl"))
    assert any(n.endswith("-drift-jev-a.jsonl") for n in runs)
    assert any(n.endswith("-drift-jev-b.jsonl") for n in runs)


def test_drift_builds_control_chart_with_alarm(tmp_path, monkeypatch):
    DriftTarget.built = []
    # 100 probes -> 10 batches of 10; first 8 stable, batch 9 fully disagrees.
    DriftTarget.FLIP = {f"p{i:03d}" for i in range(80, 90)}
    monkeypatch.setattr(jr, "JevTarget", DriftTarget)
    monkeypatch.setattr(jr, "hydrate_env_from_user_scope", lambda: [])
    c = noul_contract(tmp_path / "g", rows=_many_rows(100), flag="remedy_q")
    out = jr.drift(c, "jev-a", "jev-b", reports_dir=str(tmp_path / "r"), workers=8)
    chart = out["control_chart"]
    assert chart["series"][:8] == [0.0] * 8
    assert chart["series"][8] == 1.0 and chart["series"][9] == 0.0
    assert {"center", "ucl", "lcl"} <= set(chart)
    assert [p["t"] for p in chart["points"]] == [8, 9]
    assert chart["points"][0]["alarm"] is True and chart["points"][0]["value"] == 1.0


def test_drift_without_paired_records_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(jr, "JevTarget", FakeJevTargetClass)
    monkeypatch.setattr(jr, "hydrate_env_from_user_scope", lambda: [])
    c = noul_contract(tmp_path / "g", flag="remedy_q")
    calls = {"n": 0}

    def fake_execute(contract, target, **kw):
        calls["n"] += 1
        run_index = 0 if calls["n"] == 1 else 5
        return [rec("v1", run_index, both(0.9))]

    monkeypatch.setattr(jr, "execute", fake_execute)
    with pytest.raises(RunError, match="drift: no paired records"):
        jr.drift(c, "jev-a", "jev-b", reports_dir=str(tmp_path / "r"))


# -------------------------------------------------------------------- output ---
def test_print_summary_drops_confusions_key_and_fail_returns_one(capsys):
    jr.print_summary({"a": 1, "confusions_expected_to_chosen": {"x": 1}, "when": datetime(2026, 1, 1)})
    out = json.loads(capsys.readouterr().out)
    assert out["a"] == 1 and "confusions_expected_to_chosen" not in out
    assert out["when"].startswith("2026-01-01")
    assert jr.fail("bad thing") == 1
    assert capsys.readouterr().err == "FAIL: bad thing\n"
