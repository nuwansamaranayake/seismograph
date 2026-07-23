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
    wording = contract.allowed_variation[0].field if contract.allowed_variation else ""
    embedder = HashingEmbedder()

    series = []
    for t in range(points):
        worst = 0.0
        for entry in plan.entries:
            if entry.perturbation is not Perturbation.repeat_run:
                continue
            samples = collect(entry, probe_inputs[entry.probe_id], sut, t=t, seed=seed)
            m = canonicalize(samples, equal_fields, jaccard_fields, wording, embedder)
            if m.flip_rate:
                worst = max(worst, *m.flip_rate.values())
        series.append(worst)

    threshold = contract.gate.max_decision_flip_rate
    latest = series[-1] if series else 0.0
    gate = "pass" if latest <= threshold else "block"

    lines = [
        f"# Seismograph report — {contract.contract}",
        "",
        f"plan `{plan.plan_id}` | sut `{sut_name}` | points {points} | seed {seed}",
        "",
        f"latest worst flip rate: {latest:.4f}  (gate threshold {threshold})  -> **{gate.upper()}**",
        "",
    ]
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
