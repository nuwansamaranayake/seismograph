"""Jev contract loading and deterministic scoring, no network."""
from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from app.engine.contracts import compile_plan, load_contract
from app.jev import JevAnswer, JevCallRecord
from app.jev_runner import calibration_points, summarize

QA_YAML = """
contract: qa-mini
subject: t
sut: {adapter: jev, model: jev-1.13}
golden:
  path: golden.jsonl
  kind: noul_flag
  positive_label: violation
  type_to_question: {remedy: prescribes_remedy}
questions:
  prescribes_remedy: {type: noul, instructions: "Remedy?"}
  other: {type: noul, instructions: "Other?"}
invariants:
  - {field: flagged, under: [repeat_run], relation: equal}
run_policy: {samples: 2, configs: 1, confidence: 0.95}
gate: {confidence_cutoff: 0.7, min_recall: 0.95, max_false_positive_rate: 0.10, max_decision_flip_rate: 1.0}
"""


def _rec(probe, run, answers):
    return JevCallRecord(target_id="jev:x", adapter="jev", route="/v1/systemone", arguments_hash="h",
                         latency_ms=10, model="typesafe/jev-1.13", probe_id=probe, run_index=run,
                         answers=answers, input_tokens=100, output_tokens=5, usage_cost=1e-5,
                         created_at=datetime.now(UTC))


def _noul(qid, p):
    return JevAnswer(qid, "noul", p, {"true": p, "false": 1 - p}, max(p, 1 - p))


def test_golden_rows_become_probes_with_expected(tmp_path):
    rows = [
        {"id": "v1", "label": "violation", "violation_type": "remedy", "text": "wear a ring"},
        {"id": "c1", "label": "clean", "violation_type": None, "text": "the moon is bright"},
    ]
    (tmp_path / "golden.jsonl").write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    c = load_contract(QA_YAML, base_dir=tmp_path)
    assert [p.id for p in c.probes] == ["v1", "c1"]
    assert c.probes[0].expected == {"label": "violation", "violation_type": "remedy"}
    plan = compile_plan(c)
    assert len(plan.entries) == 2 and all(e.samples == 2 for e in plan.entries)


def test_golden_contract_without_file_refuses(tmp_path):
    with pytest.raises(ValueError, match="golden"):
        load_contract(QA_YAML, base_dir=tmp_path)


def test_summarize_scores_against_ground_truth(tmp_path):
    rows = [
        {"id": "v1", "label": "violation", "violation_type": "remedy", "text": "a"},
        {"id": "c1", "label": "clean", "violation_type": None, "text": "b"},
        {"id": "c2", "label": "clean", "violation_type": None, "text": "c"},
    ]
    (tmp_path / "golden.jsonl").write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    c = load_contract(QA_YAML, base_dir=tmp_path)
    records = [
        _rec("v1", 0, {"prescribes_remedy": _noul("prescribes_remedy", 0.9), "other": _noul("other", 0.1)}),
        _rec("v1", 1, {"prescribes_remedy": _noul("prescribes_remedy", 0.8), "other": _noul("other", 0.2)}),
        _rec("c1", 0, {"prescribes_remedy": _noul("prescribes_remedy", 0.1), "other": _noul("other", 0.1)}),
        _rec("c1", 1, {"prescribes_remedy": _noul("prescribes_remedy", 0.75), "other": _noul("other", 0.1)}),  # false positive
        _rec("c2", 0, {"prescribes_remedy": _noul("prescribes_remedy", 0.0), "other": _noul("other", 0.0)}),
        _rec("c2", 1, {"prescribes_remedy": _noul("prescribes_remedy", 0.0), "other": _noul("other", 0.0)}),
    ]
    s = summarize(c, records)
    m = s["metrics"]
    assert m["recall"] == 1.0
    assert m["false_positive_rate"] == pytest.approx(0.25)
    assert m["recall_by_type_matching_question"] == {"remedy": 1.0}
    assert m["flip_rate_worst"] == pytest.approx(0.5)  # c1 flipped once in two runs
    assert s["passed"] is False  # FPR 0.25 > 0.10
    assert s["usage"]["cost_usd"] == pytest.approx(6e-5)

    pts = calibration_points(c, records)
    # 6 records x 2 nouls = 12 points; confidence is max(p, 1-p)
    assert len(pts) == 12
    conf, ok = pts[0]
    assert conf == pytest.approx(0.9) and ok is True
