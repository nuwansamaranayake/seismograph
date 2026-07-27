"""CLI report: run a contract against a SUT in-process and print/write a markdown report.

Usage:
    python -m app.cli run --contract path/to/contract.yaml --sut stable --points 12
                          [--report out.md] [--seed 7]

Useful in CI on day one: exits nonzero when the contract gate blocks, so a pipeline can
fail on consistency regressions without any server or database.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .engine.canonicalize import canonicalize
from .engine.charts import IndividualsChart
from .engine.contracts import Perturbation, Relation, compile_plan, load_contract
from .engine.embedding import HashingEmbedder
from .engine.sampler import collect
from .engine.suts import DEMO_SUTS

BASELINE_MIN = 8


def run(contract_path: str, sut_name: str, points: int, seed: int,
        report_path: str | None) -> int:
    sut = DEMO_SUTS.get(sut_name)
    if sut is None:
        print(f"unknown sut '{sut_name}'; available: {sorted(DEMO_SUTS)}", file=sys.stderr)
        return 2
    contract = load_contract(Path(contract_path).read_text(encoding="utf-8"))
    plan = compile_plan(contract)
    probe_inputs = {p.id: p.input for p in contract.probes}
    equal_fields = [i.field for i in contract.invariants if i.relation is Relation.equal]
    jaccard_fields = [i.field for i in contract.invariants
                      if i.relation is Relation.jaccard_at_least]
    jaccard_thresholds = {i.field: i.threshold for i in contract.invariants
                          if i.relation is Relation.jaccard_at_least}
    wording = contract.allowed_variation[0].field if contract.allowed_variation else ""
    embedder = HashingEmbedder()

    executable = [e for e in plan.entries if e.perturbation is Perturbation.repeat_run]
    if not executable:
        # A gate over zero measurements would be a recorded pass over nothing (Standard 3:
        # a plan cell is never silently skipped). Fail loud instead of deriving a gate.
        print("contract has no executable plan cells (paraphrase-only contracts need "
              "generated variants; lands in M8)", file=sys.stderr)
        return 2

    series = []
    latest_malformed = 0.0
    latest_jaccard_failures: list[tuple[str, str, float, float]] = []
    for t in range(points):
        worst = 0.0
        worst_mal = 0.0
        j_failures: list[tuple[str, str, float, float]] = []
        for entry in executable:
            samples = collect(entry, probe_inputs[entry.probe_id], sut, t=t, seed=seed)
            m = canonicalize(samples, equal_fields, jaccard_fields, wording, embedder)
            if m.flip_rate:
                worst = max(worst, *m.flip_rate.values())
            worst_mal = max(worst_mal, m.malformed_rate)
            for f, min_j in jaccard_thresholds.items():
                observed = m.jaccard_mean.get(f)
                if observed is not None and observed < min_j:
                    j_failures.append((entry.probe_id, f, observed, min_j))
        series.append(worst)
        latest_malformed = worst_mal
        latest_jaccard_failures = j_failures

    threshold = contract.gate.max_decision_flip_rate
    mal_threshold = contract.gate.max_malformed_rate
    latest = series[-1]
    gate = "pass"
    if latest > threshold or latest_malformed > mal_threshold or latest_jaccard_failures:
        gate = "block"

    lines = [
        f"# Seismograph report — {contract.contract}",
        "",
        f"plan `{plan.plan_id}` | sut `{sut_name}` | points {points} | seed {seed}",
        "",
        f"latest worst flip rate: {latest:.4f}  (gate threshold {threshold})  -> **{gate.upper()}**",
        f"latest malformed rate: {latest_malformed:.4f}  (gate threshold {mal_threshold})",
    ]
    for probe_id, f, observed, min_j in latest_jaccard_failures:
        lines.append(f"jaccard invariant FAILED: probe `{probe_id}` field `{f}` "
                     f"mean {observed:.4f} < declared threshold {min_j}")
    lines.append("")
    if len(series) >= BASELINE_MIN + 1:
        chart = IndividualsChart(series[:BASELINE_MIN])
        lines += ["| t | value | ucl | alarm |", "|---|---|---|---|"]
        for i, v in enumerate(series[BASELINE_MIN:], start=BASELINE_MIN):
            p = chart.add(i, v)
            lines.append(f"| {p.t} | {p.value:.4f} | {p.ucl:.4f} | "
                         f"{p.rule or '-' if p.alarm else '-'} |")
    else:
        lines.append(f"(control chart warms up after {BASELINE_MIN} points; "
                     f"have {len(series)})")
    text = "\n".join(lines) + "\n"
    if report_path:
        Path(report_path).write_text(text, encoding="utf-8", newline="\n")
    print(text)
    return 0 if gate == "pass" else 1


def main() -> None:
    ap = argparse.ArgumentParser(prog="seismograph")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="run a contract against a demo SUT and report")
    r.add_argument("--contract", required=True)
    r.add_argument("--sut", default="stable")
    r.add_argument("--points", type=int, default=12)
    r.add_argument("--seed", type=int, default=7)
    r.add_argument("--report", default=None)
    args = ap.parse_args()
    sys.exit(run(args.contract, args.sut, args.points, args.seed, args.report))


if __name__ == "__main__":
    main()
