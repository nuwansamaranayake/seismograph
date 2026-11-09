"""`seismo gate`: the release gate, as one command a CI job can run.

    seismo gate --contract contracts/refund.yaml --sut my_app.eval:sut --points 12

Runs every executable cell of the contract at each of `points` time steps, decides the
gate on the latest one with engine.execute (the same code the API uses), and writes a
markdown summary a reviewer can read on the pull request.

Exit codes are the interface:
    0  gate passed
    1  gate blocked (or, with --fail-on alarm, the control chart alarmed on the latest point)
    2  the gate could not be evaluated: bad contract, unknown system, nothing measurable

`--sut` is a simulator name, or `package.module:attribute` naming your own system: any
object with `run(probe_input: str, t: int, rng: random.Random) -> str` returning JSON
text. A class is instantiated with no arguments.
"""
from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path

from .engine import modes as mode_engine
from .engine.charts import IndividualsChart
from .engine.contracts import compile_plan, load_contract
from .engine.embedding import HashingEmbedder
from .engine.execute import NothingMeasured, RunOutcome, execute_plan
from .engine.suts import DEMO_SUTS, SUT_CATALOG

BASELINE_MIN = 8


class GateConfigError(Exception):
    """The gate could not be evaluated. Exit code 2."""


def resolve_sut(name: str):
    if name in DEMO_SUTS:
        return DEMO_SUTS[name]
    module_name, sep, attr = name.partition(":")
    # The caller's module lives in the directory the gate is run from. It is appended, not
    # prepended: a caller project with its own top-level `app` package must not shadow the
    # installed one this program is made of.
    if os.getcwd() not in sys.path:
        sys.path.append(os.getcwd())
    if not sep:
        raise GateConfigError(
            f"unknown sut '{name}'. Use a simulator ({', '.join(sorted(DEMO_SUTS))}) "
            "or package.module:attribute")
    try:
        target = getattr(importlib.import_module(module_name), attr)
    except (ImportError, AttributeError) as e:
        raise GateConfigError(f"cannot load sut '{name}': {e}") from e
    sut = target() if isinstance(target, type) else target
    if not callable(getattr(sut, "run", None)):
        raise GateConfigError(f"sut '{name}' has no run(probe_input, t, rng) method")
    return sut


def _chart_rows(series: list[float]) -> list[str]:
    if len(series) <= BASELINE_MIN:
        return [f"Control chart warms up after {BASELINE_MIN} points. Have {len(series)}."]
    chart = IndividualsChart(series[:BASELINE_MIN])
    rows = ["| t | worst flip rate | upper limit | signal |", "|---|---|---|---|"]
    for i, value in enumerate(series[BASELINE_MIN:], start=BASELINE_MIN):
        p = chart.add(i, value)
        rows.append(f"| {p.t} | {p.value:.4f} | {p.ucl:.4f} | {p.rule or '-'} |")
    return rows


def latest_alarm(series: list[float]) -> bool:
    if len(series) <= BASELINE_MIN:
        return False
    chart = IndividualsChart(series[:BASELINE_MIN])
    point = None
    for i, value in enumerate(series[BASELINE_MIN:], start=BASELINE_MIN):
        point = chart.add(i, value)
    return bool(point and point.alarm)


def summary(contract_name: str, plan_id: str, sut_name: str, points: int, seed: int,
            outcomes: list[RunOutcome], verdict: str) -> str:
    latest = outcomes[-1]
    lines = [
        f"## Seismograph gate: {verdict.upper()}",
        "",
        f"Contract `{contract_name}`, plan `{plan_id}`, system `{sut_name}`, "
        f"{points} points, seed {seed}.",
    ]
    if sut_name in SUT_CATALOG:
        lines.append("")
        lines.append(f"`{sut_name}` is a built-in simulator, not your system. "
                     f"{SUT_CATALOG[sut_name]['summary']}")
    lines += ["", "### Why"]
    lines += [f"- {reason}" for reason in latest.reasons] or ["- every declared tolerance held"]
    lines += ["", "### Latest point, by cell", "",
              "| probe | perturbation | n | flip rate | malformed | jaccard |",
              "|---|---|---|---|---|---|"]
    for cell in latest.cells:
        m = cell.metrics
        flip = max(m.flip_rate.values(), default=0.0)
        jaccard = ", ".join(f"{f} {v:.3f}" for f, v in sorted(m.jaccard_mean.items())) or "-"
        lines.append(f"| {m.probe_id} | {m.perturbation} | {m.n} | {flip:.4f} | "
                     f"{m.malformed_rate:.4f} | {jaccard} |")
    if latest.skipped:
        lines += ["", "### Not measured"]
        lines += [f"- {s['probe']} / {s['perturbation']}: {s['reason']}" for s in latest.skipped]

    pooled: dict[tuple[str, str], list] = {}
    for outcome in outcomes[-12:]:
        for cell in outcome.cells:
            if cell.modes is not None:
                key = (cell.metrics.probe_id, cell.metrics.perturbation)
                pooled.setdefault(key, []).append(cell.modes)
    second = [(key, mode_engine.pool(reports)) for key, reports in sorted(pooled.items())]
    detected = [(key, r) for key, r in second if r.second_mode_detected]
    if detected:
        lines += ["", "### Second outcome mode", ""]
        for (probe, perturbation), report in detected:
            lines.append(f"- {probe} / {perturbation}: {report.second_mode_share:.1%} of "
                         f"{report.n} samples take a second route "
                         f"(Wilson 95% lower bound {report.second_mode_low:.1%})")

    lines += ["", "### Control chart", ""]
    lines += _chart_rows([o.worst_flip_rate for o in outcomes])
    return "\n".join(lines) + "\n"


def gate(contract_path: str, sut_name: str, points: int, seed: int,
         summary_path: str | None = None, fail_on: str = "gate") -> int:
    try:
        sut = resolve_sut(sut_name)
        try:
            contract = load_contract(Path(contract_path).read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            raise GateConfigError(f"cannot load contract {contract_path}: {e}") from e
        if points < 1:
            raise GateConfigError("--points must be at least 1")
        plan = compile_plan(contract)
        try:
            outcomes = [execute_plan(contract, plan.entries, sut, t=t, seed=seed,
                                     embedder=HashingEmbedder()) for t in range(points)]
        except NothingMeasured as e:
            raise GateConfigError(str(e)) from e
    except GateConfigError as e:
        print(f"seismo gate: {e}", file=sys.stderr)
        return 2

    blocked = outcomes[-1].decision == "block"
    alarmed = fail_on == "alarm" and latest_alarm([o.worst_flip_rate for o in outcomes])
    verdict = "block" if blocked or alarmed else "pass"
    text = summary(contract.contract, plan.plan_id, sut_name, points, seed, outcomes, verdict)
    if alarmed and not blocked:
        text += "\nBlocked by `--fail-on alarm`: the control chart signalled on the latest point.\n"
    target = summary_path or os.environ.get("GITHUB_STEP_SUMMARY", "").strip()
    if target:
        with open(target, "a", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
    print(text)
    return 1 if verdict == "block" else 0
