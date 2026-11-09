"""CLI report: run a contract against a SUT, or a suite against a live target.

Usage:
    seismo run --contract path/to/contract.yaml --sut stable --points 12
               [--report out.md] [--seed 7]
    seismo run --suite kalika --profile daily --fail-on drift
    seismo run --contract kalika-qa-gate            # golden-set contract, Jev SUT
    seismo calibrate --contract kalika-qa-gate      # per-bin accuracy and ECE
    seismo drift --contract kalika-qa-gate --model-a jev-1.13 --model-b jev-latest

`python -m seismograph ...` is the same program (seismograph/__main__.py).

Useful in CI on day one: exits nonzero when the contract gate blocks, so a pipeline can
fail on consistency regressions without any server or database. The suite form is the
deploy-pipeline command (docs/gates-spec.md g4) — it calls a real target, checks every
declared layer, compares against the committed baseline, and mails one alert on any
failure, drift, or incomplete layer.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

from .engine.charts import IndividualsChart
from .engine.contracts import compile_plan, load_contract
from .engine.embedding import HashingEmbedder
from .engine.execute import NothingMeasured, execute_plan
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
    try:
        # Every executable cell, through the same executor as the API and `seismo gate`.
        # This command used to run repeat_run cells only, which was right while they were
        # the only executable ones and became a silent skip once Phase 2 gave irrelevance,
        # order, format and monotonicity their generators (Standard 3).
        outcomes = [execute_plan(contract, plan.entries, sut, t=t, seed=seed,
                                 embedder=HashingEmbedder()) for t in range(points)]
    except NothingMeasured:
        # A gate over zero measurements would be a recorded pass over nothing (Standard 3:
        # a plan cell is never silently skipped). Fail loud instead of deriving a gate.
        print("contract has no executable plan cells (paraphrase-only contracts need "
              "generated variants)", file=sys.stderr)
        return 2
    if not outcomes:
        print("--points must be at least 1", file=sys.stderr)
        return 2

    series = [o.worst_flip_rate for o in outcomes]
    latest = outcomes[-1]
    threshold = contract.gate.max_decision_flip_rate
    mal_threshold = contract.gate.max_malformed_rate
    gate = latest.decision

    lines = [
        f"# Seismograph report — {contract.contract}",
        "",
        f"plan `{plan.plan_id}` | sut `{sut_name}` | points {points} | seed {seed}",
        "",
        f"latest worst flip rate: {latest.worst_flip_rate:.4f}  (gate threshold {threshold})"
        f"  -> **{gate.upper()}**",
        f"latest malformed rate: {latest.worst_malformed_rate:.4f}  (gate threshold {mal_threshold})",
    ]
    for failure in latest.jaccard_failures:
        lines.append(f"jaccard invariant FAILED: probe `{failure['probe']}` field `{failure['field']}` "
                     f"mean {failure['jaccard_mean']:.4f} < declared threshold {failure['threshold']}")
    for cell in latest.skipped:
        lines.append(f"not measured: probe `{cell['probe']}` under {cell['perturbation']}: "
                     f"{cell['reason']}")
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


def _alert_body(result, report_link: str) -> str:
    lines = [
        f"Suite {result.suite} / profile {result.profile} against target "
        f"{result.target_id} did not come back clean.",
        "",
        f"failed checks : {len(result.failures)}",
        f"drifted       : {len(result.drifted)}",
        f"incomplete    : {len(result.incomplete)}",
        "",
        f"Report: {report_link}",
        "",
    ]
    for o in result.failures[:10]:
        lines.append(f"- {o.case_id} / {o.layer} ({o.check_type}): {'; '.join(o.reasons)[:200]}")
    for k in result.drifted[:10]:
        lines.append(f"- drift: {k} passed in the baseline and fails now")
    lines += [f"- incomplete: {r}" for r in result.incomplete[:10]]
    return "\n".join(lines) + "\n"


def run_suite_cli(suite_name: str, profile_name: str, fail_on: str, suites_dir: str,
                  report_path: str | None, write_baseline_flag: bool, store: bool,
                  alert: bool, target_id: str | None = None) -> int:
    """The deploy-pipeline command. Exit 0 only on a complete, clean, undrifted run."""
    from .alerts import AlertError, send_alert
    from .runner import load_baseline, report_markdown, run_suite, write_baseline
    from .suite import SuiteError, load_suite
    from .targets import HttpTarget, McpTarget, TargetConfigError

    try:
        suite = load_suite(Path(suites_dir) / suite_name)
        profile = suite.profile(profile_name)
        tid = target_id or suite.target_id
        adapter = os.environ.get("SEISMO_TARGET_ADAPTER", "http").strip().lower()
        if adapter == "http":
            target: HttpTarget | McpTarget = HttpTarget.from_env(tid)
        elif adapter == "mcp":
            target = McpTarget.from_env(tid, "CALCULATOR_MCP_URL")
        else:
            print(f"unknown SEISMO_TARGET_ADAPTER {adapter!r}; use http or mcp", file=sys.stderr)
            return 2
    except (SuiteError, TargetConfigError) as exc:
        print(f"configuration error: {exc}", file=sys.stderr)
        return 2

    judge_model = os.environ.get("SEISMO_JUDGE_MODEL", "").strip() or None
    judge = None
    if judge_model:
        from groundwork.gateway import LLMGateway  # only import when a judge is configured

        judge = LLMGateway()

    session = None
    if store:
        from .db import get_session

        session = get_session()

    baseline_path = suite.root / "baseline" / f"{tid}.json"
    try:
        from .runner import header_for

        header = header_for(suite, profile, tid, judge_model, store)
        baseline = load_baseline(baseline_path, header)
    except RuntimeError as exc:
        print(f"baseline refused: {exc}", file=sys.stderr)
        return 2

    result = run_suite(
        suite, target, profile,
        on=datetime.now(UTC).date(),
        baseline=baseline, judge=judge, judge_model=judge_model, session=session,
    )

    text = report_markdown(result)
    written = Path(report_path) if report_path else None
    if written:
        written.parent.mkdir(parents=True, exist_ok=True)
        written.write_text(text, encoding="utf-8", newline="\n")
    print(text)

    if write_baseline_flag:
        write_baseline(baseline_path, result)
        print(f"baseline written: {baseline_path}")

    bad = bool(result.failures) or bool(result.incomplete)
    if fail_on == "drift":
        bad = bad or bool(result.drifted)

    message_id = None
    alert_error = None
    if bad and alert:
        report_link = os.environ.get("SEISMO_REPORT_URL", "").strip() or (
            str(written) if written else "(no report file written; pass --report)"
        )
        subject = (
            f"[seismograph] {result.suite}/{result.profile}: "
            f"{len(result.failures)} failed, {len(result.drifted)} drifted, "
            f"{len(result.incomplete)} incomplete"
        )
        try:
            message_id = send_alert(subject, _alert_body(result, report_link))
            print(f"alert sent: resend message id {message_id}")
        except AlertError as exc:
            alert_error = str(exc)
            print(f"ALERT FAILED: {exc}", file=sys.stderr)

    print("G4_RUN " + json.dumps({
        "suite": result.suite,
        "profile": result.profile,
        "target_id": result.target_id,
        "header": result.header,
        "checks": len(result.outcomes),
        "failures": [o.key for o in result.failures],
        "drifted": result.drifted,
        "incomplete": result.incomplete,
        "unbaselined": result.unbaselined,
        "alert_message_id": message_id,
        "alert_error": alert_error,
        "exit_code": 1 if bad else 0,
    }))
    return 1 if bad else 0


def _jev_contract(arg: str):
    from .jev_runner import RunError, resolve_contract

    try:
        return resolve_contract(arg)
    except (RunError, ValueError) as exc:
        print(f"contract error: {exc}", file=sys.stderr)
        sys.exit(2)


def run_jev_cli(contract, workers: int, reports_dir: str) -> int:
    """Run a golden-set contract against its Jev SUT. Exit 0 only when the contract's
    declared gate passes on the live answers; any live failure exits 1 with the HTTP
    status and body on stderr."""
    from .jev_runner import RunError, print_summary, run_contract
    from .targets import TargetConfigError, TargetError

    try:
        summary = run_contract(contract, workers=workers, reports_dir=reports_dir)
    except TargetConfigError as exc:
        print(f"configuration error: {exc}", file=sys.stderr)
        return 2
    except (RunError, TargetError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    print_summary(summary)
    print(f"GATE {'PASS' if summary['passed'] else 'BLOCK'}: {contract.contract}")
    return 0 if summary["passed"] else 1


def calibrate_cli(contract, workers: int, reports_dir: str) -> int:
    from .jev_runner import RunError, calibrate, print_summary
    from .targets import TargetConfigError, TargetError

    try:
        out = calibrate(contract, workers=workers, reports_dir=reports_dir)
    except TargetConfigError as exc:
        print(f"configuration error: {exc}", file=sys.stderr)
        return 2
    except (RunError, TargetError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    print_summary(out)
    return 0


def drift_cli(contract, model_a: str, model_b: str, workers: int, reports_dir: str) -> int:
    from .jev_runner import RunError, drift, print_summary
    from .targets import TargetConfigError, TargetError

    try:
        out = drift(contract, model_a, model_b, workers=workers, reports_dir=reports_dir)
    except TargetConfigError as exc:
        print(f"configuration error: {exc}", file=sys.stderr)
        return 2
    except (RunError, TargetError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    print_summary(out)
    return 0


def main() -> None:
    ap = argparse.ArgumentParser(prog="seismo")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="run a contract against a demo SUT, or a suite against a target")
    r.add_argument("--contract", help="contract YAML path, or a name under contracts/")
    r.add_argument("--workers", type=int, default=8, help="parallel live calls (golden-set contracts)")
    r.add_argument("--reports-dir", default="reports")
    r.add_argument("--sut", default="stable")
    r.add_argument("--points", type=int, default=12)
    r.add_argument("--seed", type=int, default=7)
    r.add_argument("--report", default=None)
    r.add_argument("--suite", help="suite directory name under --suites-dir")
    r.add_argument("--profile", default="daily")
    r.add_argument("--fail-on", choices=["check", "drift"], default="drift")
    r.add_argument("--suites-dir", default="suites")
    r.add_argument("--target-id", default=None,
                   help="target identity: picks the SEISMO_TARGET_<ID>_* env vars and "
                        "the baseline file (default: the suite's target id)")
    r.add_argument("--write-baseline", action="store_true",
                   help="record this run as the baseline for the target")
    r.add_argument("--store", action="store_true",
                   help="persist every target call to Postgres (DATABASE_URL)")
    r.add_argument("--no-alert", dest="alert", action="store_false", default=True)

    c = sub.add_parser("calibrate", help="per-confidence-bin accuracy and ECE for a golden-set contract")
    c.add_argument("--contract", required=True)
    c.add_argument("--workers", type=int, default=8)
    c.add_argument("--reports-dir", default="reports")

    d = sub.add_parser("drift", help="agreement and control chart between two models on one contract")
    d.add_argument("--contract", required=True)
    d.add_argument("--model-a", required=True)
    d.add_argument("--model-b", required=True)
    d.add_argument("--workers", type=int, default=8)
    d.add_argument("--reports-dir", default="reports")

    g = sub.add_parser("gate", help="the CI release gate: every invariant, exit 0 pass, 1 block, 2 error")
    g.add_argument("--contract", required=True, help="contract YAML path")
    g.add_argument("--sut", default="stable", help="simulator name, or package.module:attribute")
    g.add_argument("--points", type=int, default=12)
    g.add_argument("--seed", type=int, default=7)
    g.add_argument("--summary", default=None,
                   help="markdown summary path (default: $GITHUB_STEP_SUMMARY when set)")
    g.add_argument("--fail-on", choices=["gate", "alarm"], default="gate")

    args = ap.parse_args()
    if args.cmd == "gate":
        from .gate_cli import gate

        sys.exit(gate(args.contract, args.sut, args.points, args.seed, args.summary, args.fail_on))
    if args.cmd == "calibrate":
        contract, _ = _jev_contract(args.contract)
        sys.exit(calibrate_cli(contract, args.workers, args.reports_dir))
    if args.cmd == "drift":
        contract, _ = _jev_contract(args.contract)
        sys.exit(drift_cli(contract, args.model_a, args.model_b, args.workers, args.reports_dir))
    if bool(args.contract) == bool(args.suite):
        ap.error("pass exactly one of --contract or --suite")
    if args.suite:
        sys.exit(run_suite_cli(args.suite, args.profile, args.fail_on, args.suites_dir,
                               args.report, args.write_baseline, args.store, args.alert,
                               args.target_id))
    from .jev_runner import is_jev_contract

    contract, path = _jev_contract(args.contract)
    if is_jev_contract(contract):
        sys.exit(run_jev_cli(contract, args.workers, args.reports_dir))
    sys.exit(run(str(path), args.sut, args.points, args.seed, args.report))


if __name__ == "__main__":
    main()
