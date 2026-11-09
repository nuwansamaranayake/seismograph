"""Run, calibrate and drift-compare a Jev-backed contract.

A contract whose `sut.adapter` is `jev` carries a golden set (probes with
ground truth) and a map of typed questions. This module executes the plan the
contract compiles to, stores every call as a run record, and decides the gate
deterministically from the recorded answers. The model proposes probabilities;
code decides.

Outputs under reports/<contract>/:
    runs/<run_id>.jsonl   one JevCallRecord per line (the run records)
    run.json              the latest run summary and gate decision
    calibration.json      per-confidence-bin count, accuracy, ECE
    drift.json            model A vs model B agreement and control chart data
"""
from __future__ import annotations

import json
import math
import statistics
import sys
from collections.abc import Sequence
from concurrent.futures import FIRST_EXCEPTION, ThreadPoolExecutor, wait
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .engine.charts import IndividualsChart
from .engine.contracts import (
    Contract,
    GoldenSpec,
    Perturbation,
    SutSpec,
    compile_plan,
    load_contract,
)
from .jev import JevCallRecord, JevTarget, hydrate_env_from_user_scope

DEFAULT_WORKERS = 8
COST_BUDGET_USD = 2.0
# Measured 2026-09-21 on jev-1.13 through OpenRouter: 2.3436e-05 USD for 558 input
# tokens (a local smoke test). Used only for the pre-run estimate.
USD_PER_INPUT_TOKEN = 2.3436e-05 / 558
CHARS_PER_TOKEN = 4.0
CALIBRATION_BINS = [(0.5, 0.6), (0.6, 0.7), (0.7, 0.8), (0.8, 0.9), (0.9, 1.0)]
CHART_BATCH = 10


class RunError(RuntimeError):
    """The run could not complete honestly: a live call failed, the budget would be
    exceeded, or the contract is not a Jev contract."""


def resolve_contract(arg: str, contracts_dir: str = "contracts") -> tuple[Contract, Path]:
    """`--contract` takes a path or a name; a name resolves to contracts/<name>.yaml."""
    path = Path(arg)
    if not path.exists():
        path = Path(contracts_dir) / f"{arg}.yaml"
    if not path.exists():
        raise RunError(f"contract not found: {arg!r} (looked for {path})")
    contract = load_contract(path.read_text(encoding="utf-8"), base_dir=path.parent)
    return contract, path


def is_jev_contract(contract: Contract) -> bool:
    return contract.sut is not None and contract.sut.adapter == "jev"


def _require_jev(contract: Contract) -> None:
    if not is_jev_contract(contract):
        raise RunError(f"contract {contract.contract} has no jev sut; nothing to run here")
    if not contract.questions:
        raise RunError(f"contract {contract.contract} declares no questions")
    if contract.golden is None:
        raise RunError(f"contract {contract.contract} declares no golden set")
    if len(contract.probes) < contract.golden.min_rows:
        raise RunError(
            f"golden set has {len(contract.probes)} labeled rows; contract requires at least "
            f"{contract.golden.min_rows}. Not running."
        )


def _golden(contract: Contract) -> GoldenSpec:
    """The golden-set section. Scoring functions take a contract _require_jev has
    accepted; this states that requirement where the section is used."""
    if contract.golden is None:
        raise RunError(f"contract {contract.contract} declares no golden set")
    return contract.golden


def _sut(contract: Contract) -> SutSpec:
    if contract.sut is None:
        raise RunError(f"contract {contract.contract} has no sut; nothing to run here")
    return contract.sut


def _questions(contract: Contract) -> dict[str, dict]:
    if not contract.questions:
        raise RunError(f"contract {contract.contract} declares no questions")
    return contract.questions


def _declared(value: float | None, name: str) -> float:
    """A gate threshold the contract must declare for the way it is scored."""
    if value is None:
        raise RunError(f"contract needs gate.{name}")
    return value


def estimate_cost_usd(contract: Contract, samples: int) -> tuple[int, float]:
    q_chars = len(json.dumps(contract.questions))
    chars = sum(len(p.input) + q_chars + 200 for p in contract.probes)
    calls = len(contract.probes) * samples
    return calls, chars * samples / CHARS_PER_TOKEN * USD_PER_INPUT_TOKEN


def _percentile(values: Sequence[int | float], pct: float) -> float:
    if not values:
        return float("nan")
    ordered = sorted(values)
    k = (len(ordered) - 1) * pct
    lo, hi = math.floor(k), math.ceil(k)
    if lo == hi:
        return float(ordered[lo])
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (k - lo)


def execute(contract: Contract, target: JevTarget, *, samples: int | None = None,
            workers: int = DEFAULT_WORKERS, budget_usd: float = COST_BUDGET_USD) -> list[JevCallRecord]:
    """Run every repeat_run plan cell against the target. Fails the whole run on the
    first live error; never substitutes a default answer."""
    _require_jev(contract)
    plan = compile_plan(contract)
    n = samples or contract.run_policy.samples
    cells = [e for e in plan.entries if e.perturbation is Perturbation.repeat_run]
    if not cells:
        raise RunError("contract compiles to zero repeat_run cells")
    calls, est = estimate_cost_usd(contract, n)
    print(f"plan {plan.plan_id}: {len(cells)} probes x {n} runs = {calls} live calls, "
          f"estimated {est:.4f} USD (budget {budget_usd:.2f})")
    if est > budget_usd:
        raise RunError(f"estimated cost {est:.4f} USD exceeds budget {budget_usd:.2f}; stopping before any call")
    inputs = {p.id: p.input for p in contract.probes}
    questions = _questions(contract)
    jobs = [(cell.probe_id, i) for cell in cells for i in range(n)]
    records: list[JevCallRecord] = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(target.call, inputs[pid], questions, probe_id=pid, run_index=i): (pid, i)
                   for pid, i in jobs}
        done, pending = wait(futures, return_when=FIRST_EXCEPTION)
        failed = [f for f in done if f.exception() is not None]
        if failed:
            for f in pending:
                f.cancel()
            exc = failed[0].exception()
            pid, i = futures[failed[0]]
            raise RunError(f"live call failed for probe {pid} run {i}: {exc}") from exc
        records = [f.result() for f in futures]
    records.sort(key=lambda r: (r.probe_id, r.run_index))
    return records


def _expected(contract: Contract) -> dict[str, dict]:
    return {p.id: (p.expected or {}) for p in contract.probes}


def _flag_decision(rec: JevCallRecord, cutoff: float, question: str | None = None) -> bool:
    """Flag when the named noul (or, with no name, any noul) is at or above the cutoff."""
    if question is not None:
        return float(rec.answers[question].answer) >= cutoff
    return any(a.type == "noul" and float(a.answer) >= cutoff for a in rec.answers.values())


def _flag_prob(rec: JevCallRecord, question: str | None) -> float:
    """The probability the flag decision is taken on (for cutoff sweeps)."""
    if question is not None:
        return float(rec.answers[question].answer)
    return max(float(a.answer) for a in rec.answers.values() if a.type == "noul")


def cutoff_sweep(contract: Contract, records: list[JevCallRecord], target_recall: float = 0.95,
                 step: float = 0.05) -> dict[str, Any]:
    """Recall and FPR at every cutoff; the highest cutoff that still reaches target_recall."""
    golden = _golden(contract)
    expected = _expected(contract)
    pos = golden.positive_label
    pairs = [(_flag_prob(r, golden.flag_question), expected[r.probe_id].get("label") == pos) for r in records]
    n_pos = sum(1 for _, t in pairs if t)
    n_neg = len(pairs) - n_pos
    table = []
    best = None
    k = int(round(1.0 / step))
    for i in range(1, k):
        c = round(i * step, 2)
        tp = sum(1 for p, t in pairs if t and p >= c)
        fp = sum(1 for p, t in pairs if (not t) and p >= c)
        recall = tp / n_pos if n_pos else float("nan")
        fpr = fp / n_neg if n_neg else float("nan")
        table.append({"cutoff": c, "recall": recall, "false_positive_rate": fpr})
        if n_pos and recall >= target_recall:
            best = {"cutoff": c, "recall": recall, "false_positive_rate": fpr}
    return {"target_recall": target_recall, "positives": n_pos, "negatives": n_neg,
            "cutoff_for_target_recall": best, "table": table}


def engine_disagreements(contract: Contract, records: list[JevCallRecord], cutoff: float) -> dict[str, Any]:
    """Where Jev and the incumbent engine disagree with each other, who agreed with the human?

    Uses the per-probe modal Jev decision and the golden row's `engine_level`
    (DIRECT/LIKELY counted as the engine saying "applies"). Only meaningful for
    golden sets exported from a system that recorded the engine's tier."""
    golden = _golden(contract)
    expected = _expected(contract)
    by_probe: dict[str, list[bool]] = {}
    for r in records:
        by_probe.setdefault(r.probe_id, []).append(_flag_decision(r, cutoff, golden.flag_question))
    jev_right = engine_right = both_right = both_wrong = 0
    jev_right_ids: list[str] = []
    engine_right_ids: list[str] = []
    n_with_engine = 0
    for pid, runs in by_probe.items():
        exp = expected[pid]
        level = exp.get("engine_level")
        if level is None:
            continue
        n_with_engine += 1
        jev = sum(runs) * 2 > len(runs)
        engine = level in ("DIRECT", "LIKELY")
        human = exp.get("label") == golden.positive_label
        if jev == engine:
            if jev == human:
                both_right += 1
            else:
                both_wrong += 1
        elif jev == human:
            jev_right += 1
            jev_right_ids.append(pid)
        else:
            engine_right += 1
            engine_right_ids.append(pid)
    return {"pairs_with_engine_tier": n_with_engine, "agree_both_right": both_right,
            "agree_both_wrong": both_wrong, "disagree_jev_right": jev_right,
            "disagree_engine_right": engine_right,
            "disagree_jev_right_ids": jev_right_ids[:50], "disagree_engine_right_ids": engine_right_ids[:50]}


def _choice_decision(rec: JevCallRecord, qid: str) -> str:
    return str(rec.answers[qid].answer)


def _flip_rates(decisions: dict[str, list[Any]]) -> tuple[float, float]:
    """Per probe: share of runs disagreeing with the modal decision. Returns (mean, worst)."""
    rates = []
    for runs in decisions.values():
        if not runs:
            continue
        mode = max(set(map(str, runs)), key=lambda v: sum(str(r) == v for r in runs))
        rates.append(sum(str(r) != mode for r in runs) / len(runs))
    return (statistics.fmean(rates) if rates else 0.0, max(rates) if rates else 0.0)


def summarize(contract: Contract, records: list[JevCallRecord]) -> dict[str, Any]:
    _require_jev(contract)
    golden = _golden(contract)
    gate = contract.gate
    expected = _expected(contract)
    latencies = [r.latency_ms for r in records]
    cost = sum(r.usage_cost or 0.0 for r in records)
    tokens_in = sum(r.input_tokens or 0 for r in records)
    summary: dict[str, Any] = {
        "contract": contract.contract, "model": records[0].model if records else None,
        "records": len(records), "probes": len(contract.probes),
        "samples": contract.run_policy.samples, "kind": golden.kind,
        "latency_ms": {"p50": _percentile(latencies, 0.5), "p95": _percentile(latencies, 0.95)},
        "usage": {"input_tokens": tokens_in, "cost_usd": cost},
        "gate": {}, "passed": None,
    }
    by_probe: dict[str, list[Any]] = {}
    if golden.kind == "noul_flag":
        cutoff = _declared(gate.confidence_cutoff, "confidence_cutoff")
        pos = golden.positive_label
        tp = fn = fp = tn = 0
        per_type: dict[str, list[int]] = {}
        for r in records:
            flagged = _flag_decision(r, cutoff, golden.flag_question)
            by_probe.setdefault(r.probe_id, []).append(flagged)
            exp = expected[r.probe_id]
            if exp.get("label") == pos:
                tp += flagged
                fn += not flagged
                vt = exp.get("violation_type") or "unknown"
                qid = golden.type_to_question.get(vt)
                hit = flagged if qid is None else float(r.answers[qid].answer) >= cutoff
                per_type.setdefault(vt, []).append(int(hit))
            else:
                fp += flagged
                tn += not flagged
        recall = tp / (tp + fn) if (tp + fn) else float("nan")
        fpr = fp / (fp + tn) if (fp + tn) else float("nan")
        mean_flip, worst_flip = _flip_rates(by_probe)
        summary["metrics"] = {
            "confidence_cutoff": cutoff, "flag_question": golden.flag_question,
            "recall": recall, "false_positive_rate": fpr,
            "tp": tp, "fn": fn, "fp": fp, "tn": tn,
            "recall_by_type_matching_question": {t: sum(v) / len(v) for t, v in per_type.items()},
            "flip_rate_mean": mean_flip, "flip_rate_worst": worst_flip,
            "cutoff_sweep": cutoff_sweep(contract, records, gate.min_recall or 0.95),
            "engine_disagreements": engine_disagreements(contract, records, cutoff),
        }
        summary["gate"] = {"min_recall": gate.min_recall,
                           "max_false_positive_rate": gate.max_false_positive_rate,
                           "max_decision_flip_rate": gate.max_decision_flip_rate}
        summary["passed"] = (recall >= _declared(gate.min_recall, "min_recall")
                             and fpr <= _declared(gate.max_false_positive_rate, "max_false_positive_rate")
                             and worst_flip <= gate.max_decision_flip_rate)
    elif golden.kind == "choice_top1":
        qid = next(q for q, spec in _questions(contract).items() if spec["type"] == "choice")
        correct = 0
        confusions: dict[str, dict[str, int]] = {}
        for r in records:
            chosen = _choice_decision(r, qid)
            by_probe.setdefault(r.probe_id, []).append(chosen)
            truth = expected[r.probe_id].get("choice")
            if chosen == truth:
                correct += 1
            else:
                confusions.setdefault(str(truth), {})
                confusions[str(truth)][chosen] = confusions[str(truth)].get(chosen, 0) + 1
        accuracy = correct / len(records) if records else float("nan")
        mean_flip, worst_flip = _flip_rates(by_probe)
        summary["metrics"] = {
            "top1_accuracy": accuracy, "correct": correct,
            "flip_rate_mean": mean_flip, "flip_rate_worst": worst_flip,
            "confusions_expected_to_chosen": confusions,
        }
        summary["gate"] = {"min_top1_accuracy": gate.min_top1_accuracy,
                           "max_decision_flip_rate": gate.max_decision_flip_rate}
        summary["passed"] = (accuracy >= _declared(gate.min_top1_accuracy, "min_top1_accuracy")
                             and worst_flip <= gate.max_decision_flip_rate)
    else:
        raise RunError(f"unknown golden kind {golden.kind!r}")
    return summary


def _reports_dir(contract: Contract, reports_dir: str) -> Path:
    d = Path(reports_dir) / contract.contract
    d.mkdir(parents=True, exist_ok=True)
    return d


def write_records(contract: Contract, records: list[JevCallRecord], reports_dir: str,
                  tag: str = "") -> Path:
    d = _reports_dir(contract, reports_dir) / "runs"
    d.mkdir(exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    path = d / f"{stamp}{('-' + tag) if tag else ''}.jsonl"
    with path.open("w", encoding="utf-8", newline="\n") as f:
        for r in records:
            f.write(json.dumps(r.to_json(), ensure_ascii=False) + "\n")
    return path


def latest_records(contract: Contract, reports_dir: str, model: str | None = None) -> list[JevCallRecord] | None:
    d = Path(reports_dir) / contract.contract / "runs"
    if not d.exists():
        return None
    for path in sorted(d.glob("*.jsonl"), reverse=True):
        rows = [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
        if not rows:
            continue
        recs = [JevCallRecord.from_json(r) for r in rows]
        if model is None or all(model.split("-")[0] in r.model for r in recs):
            ids = {p.id for p in contract.probes}
            if {r.probe_id for r in recs} == ids:
                return recs
    return None


def run_contract(contract: Contract, *, model: str | None = None, workers: int = DEFAULT_WORKERS,
                 reports_dir: str = "reports", budget_usd: float = COST_BUDGET_USD) -> dict[str, Any]:
    _require_jev(contract)
    hydrate_env_from_user_scope()
    chosen_model = model or _sut(contract).model
    with JevTarget.from_env(chosen_model, timeout=_sut(contract).timeout_seconds) as target:
        records = execute(contract, target, workers=workers, budget_usd=budget_usd)
    path = write_records(contract, records, reports_dir)
    summary = summarize(contract, records)
    summary["records_path"] = str(path)
    summary["run_at"] = datetime.now(UTC).isoformat()
    (_reports_dir(contract, reports_dir) / "run.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def calibration_points(contract: Contract, records: list[JevCallRecord]) -> list[tuple[float, bool]]:
    """(confidence, correct) per answered question, against golden ground truth."""
    golden = _golden(contract)
    expected = _expected(contract)
    points: list[tuple[float, bool]] = []
    for r in records:
        exp = expected[r.probe_id]
        for qid, a in r.answers.items():
            if a.type == "noul":
                p = float(a.answer)
                if golden.kind != "noul_flag":
                    continue
                if golden.flag_question is not None:
                    if qid != golden.flag_question:
                        continue  # the other nouls carry no ground truth in this golden set
                    truth = exp.get("label") == golden.positive_label
                else:
                    truth = (exp.get("label") == golden.positive_label
                             and golden.type_to_question.get(exp.get("violation_type") or "") == qid)
                points.append((max(p, 1.0 - p), (p >= 0.5) == truth))
            elif a.type == "choice":
                truth_choice = exp.get("choice")
                if truth_choice is None:
                    continue
                points.append((max(a.probabilities.values()), str(a.answer) == truth_choice))
    return points


def calibrate(contract: Contract, *, records: list[JevCallRecord] | None = None,
              reports_dir: str = "reports", workers: int = DEFAULT_WORKERS) -> dict[str, Any]:
    _require_jev(contract)
    source = "existing run records"
    if records is None:
        records = latest_records(contract, reports_dir, _sut(contract).model)
    if records is None:
        source = "fresh live run"
        run_contract(contract, workers=workers, reports_dir=reports_dir)
        records = latest_records(contract, reports_dir, _sut(contract).model)
        if records is None:
            raise RunError("no records after a live run")
    points = calibration_points(contract, records)
    if not points:
        raise RunError("no calibration points: golden set carries no ground truth for these questions")
    n = len(points)
    bins = []
    ece = 0.0
    for lo, hi in CALIBRATION_BINS:
        inb = [(c, ok) for c, ok in points if (lo <= c < hi) or (hi == 1.0 and c == 1.0)]
        count = len(inb)
        acc: float | None = None
        conf: float | None = None
        gap: float | None = None
        if count:
            acc = sum(ok for _, ok in inb) / count
            conf = statistics.fmean(c for c, _ in inb)
            gap = abs(acc - conf)
            ece += count / n * gap
        bins.append({"bin": f"{lo:.1f}-{hi:.1f}", "count": count, "accuracy": acc,
                     "mean_confidence": conf, "abs_gap": gap})
    out = {
        "contract": contract.contract, "model": records[0].model, "source": source,
        "points": n, "records": len(records),
        "bins": bins, "expected_calibration_error": ece,
        "computed_at": datetime.now(UTC).isoformat(),
    }
    if _golden(contract).kind == "noul_flag":
        # The cutoff that reaches the contract's recall target on this data, with its FPR.
        out["cutoff_sweep"] = cutoff_sweep(contract, records, contract.gate.min_recall or 0.95)
    (_reports_dir(contract, reports_dir) / "calibration.json").write_text(
        json.dumps(out, indent=2), encoding="utf-8")
    return out


def _decisions(contract: Contract, rec: JevCallRecord) -> dict[str, Any]:
    cutoff = contract.gate.confidence_cutoff if contract.gate.confidence_cutoff is not None else 0.5
    return {qid: a.decision(cutoff) for qid, a in rec.answers.items()}


def drift(contract: Contract, model_a: str, model_b: str, *, reports_dir: str = "reports",
          workers: int = DEFAULT_WORKERS, budget_usd: float = COST_BUDGET_USD) -> dict[str, Any]:
    """Run the same golden set on two models and measure agreement per question,
    plus a control chart over per-batch disagreement (batches of CHART_BATCH probes,
    first 8 batches set the limits, the rest are monitored)."""
    _require_jev(contract)
    hydrate_env_from_user_scope()
    runs: dict[str, list[JevCallRecord]] = {}
    for m in (model_a, model_b):
        with JevTarget.from_env(m, timeout=_sut(contract).timeout_seconds) as target:
            runs[m] = execute(contract, target, workers=workers, budget_usd=budget_usd)
        write_records(contract, runs[m], reports_dir, tag=f"drift-{m}")
    a_by = {(r.probe_id, r.run_index): r for r in runs[model_a]}
    b_by = {(r.probe_id, r.run_index): r for r in runs[model_b]}
    keys = sorted(set(a_by) & set(b_by))
    if not keys:
        raise RunError("drift: no paired records")
    per_q: dict[str, dict[str, Any]] = {}
    per_probe_disagree: dict[str, list[int]] = {}
    for k in keys:
        da, db = _decisions(contract, a_by[k]), _decisions(contract, b_by[k])
        any_dis = 0
        for qid in _questions(contract):
            agree = da[qid] == db[qid]
            any_dis |= not agree
            slot = per_q.setdefault(qid, {"agree": 0, "n": 0, "abs_prob_diff": []})
            slot["agree"] += agree
            slot["n"] += 1
            pa, pb = a_by[k].answers[qid].probabilities, b_by[k].answers[qid].probabilities
            slot["abs_prob_diff"].append(sum(abs(pa.get(o, 0.0) - pb.get(o, 0.0)) for o in set(pa) | set(pb)) / 2)
        per_probe_disagree.setdefault(k[0], []).append(any_dis)
    per_question = {
        qid: {"agreement_rate": s["agree"] / s["n"], "n_pairs": s["n"],
              "mean_total_variation": statistics.fmean(s["abs_prob_diff"])}
        for qid, s in per_q.items()
    }
    overall = statistics.fmean(v["agreement_rate"] for v in per_question.values())
    probe_ids = sorted(per_probe_disagree)
    series = []
    for i in range(0, len(probe_ids), CHART_BATCH):
        batch = probe_ids[i:i + CHART_BATCH]
        vals = [x for pid in batch for x in per_probe_disagree[pid]]
        series.append(sum(vals) / len(vals))
    chart: dict[str, Any] = {"batch_size": CHART_BATCH, "series": series, "baseline_points": min(8, len(series)),
                             "points": []}
    if len(series) >= 9:
        ic = IndividualsChart(series[:8])
        chart.update({"center": ic.center, "ucl": ic.ucl, "lcl": ic.lcl})
        for t, v in enumerate(series[8:], start=8):
            p = ic.add(t, v)
            chart["points"].append({"t": p.t, "value": p.value, "center": p.center, "ucl": p.ucl,
                                    "lcl": p.lcl, "alarm": p.alarm, "rule": p.rule})
    else:
        chart["note"] = f"control chart needs 9+ batches; have {len(series)}"
    out = {
        "contract": contract.contract, "model_a": model_a, "model_b": model_b,
        "model_a_served": runs[model_a][0].model, "model_b_served": runs[model_b][0].model,
        "samples": contract.run_policy.samples, "pairs": len(keys),
        "per_question": per_question, "overall_agreement": overall,
        "control_chart": chart,
        "usage": {m: {"cost_usd": sum(r.usage_cost or 0.0 for r in rs),
                      "latency_p50_ms": _percentile([r.latency_ms for r in rs], 0.5),
                      "latency_p95_ms": _percentile([r.latency_ms for r in rs], 0.95)}
                  for m, rs in runs.items()},
        "computed_at": datetime.now(UTC).isoformat(),
    }
    (_reports_dir(contract, reports_dir) / "drift.json").write_text(
        json.dumps(out, indent=2), encoding="utf-8")
    return out


def print_summary(summary: dict[str, Any]) -> None:
    print(json.dumps({k: v for k, v in summary.items() if k != "confusions_expected_to_chosen"},
                     indent=2, default=str))


def fail(msg: str) -> int:
    print(f"FAIL: {msg}", file=sys.stderr)
    return 1
