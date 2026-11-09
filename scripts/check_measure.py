"""Measure all three check types against their labelled sets. g2's evidence.

Runs every sample in data/checks/, counts how often each check type catches a
planted defect (sensitivity) and how often it fires on a clean sample (the
false-alarm rate), and reports both with a 95% Wilson interval. Writes
check_report.md and check_report.json.

Thresholds live in EVAL.md and are read from there, not restated here, so there
is one place to change them and that change is visible in a diff. A run that
misses a threshold reports the miss and exits non-zero. Never adjust a threshold
to make a run pass (docs/gates-spec.md g2).

Refuse rates over zero samples: wilson() raises on n=0 by construction, and a
check type whose set is empty is a failure, not a 0%.

  python scripts/check_measure.py
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.checks import (  # noqa: E402
    RUBRIC_TEXT,
    RUBRIC_VERSION,
    run_assert_check,
    run_grounded_check,
    run_rubric_check,
)
from app.engine.golden import wilson  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
SETS = ROOT / "data" / "checks"
REPORT_MD = ROOT / "check_report.md"
REPORT_JSON = ROOT / "check_report.json"
EVAL_DOC = ROOT / "EVAL.md"
VERSION = "v1"

TYPES = ("assert", "grounded", "rubric")


def read_thresholds() -> dict:
    """Parse the g2 threshold table out of EVAL.md — one source of truth.

    Row format, inside the g2 section:
      | assert | 0.95 | 0.05 |
    """
    text = EVAL_DOC.read_text(encoding="utf-8")
    block = re.search(
        r"<!-- g2-thresholds:start -->(.*?)<!-- g2-thresholds:end -->", text, re.DOTALL
    )
    if not block:
        raise SystemExit("check_measure: EVAL.md has no g2-thresholds block. Refusing to "
                         "invent thresholds at run time.")
    out = {}
    for row in re.finditer(r"^\|\s*(\w+)\s*\|\s*([0-9.]+)\s*\|\s*([0-9.]+)\s*\|",
                           block.group(1), re.MULTILINE):
        out[row.group(1)] = {"min_sensitivity": float(row.group(2)),
                             "max_false_alarm": float(row.group(3))}
    missing = [t for t in TYPES if t not in out]
    if missing:
        raise SystemExit(f"check_measure: EVAL.md thresholds missing for {missing}")
    return out


def load_set(name: str) -> dict:
    path = SETS / f"{name}_set.{VERSION}.json"
    if not path.exists():
        raise SystemExit(f"check_measure: {path} missing. Run scripts/build_check_sets.py.")
    return json.loads(path.read_text(encoding="utf-8"))


def measure(check_type: str, samples: list[dict], runner) -> dict:
    """runner(sample) -> (passed: bool, reasons: list[str])."""
    planted = [s for s in samples if s["label"] == "planted"]
    clean = [s for s in samples if s["label"] == "clean"]
    if not planted or not clean:
        raise SystemExit(f"check_measure: {check_type} set has no {'planted' if not planted else 'clean'} samples")

    caught, false_alarms, rows = 0, 0, []
    for sample in samples:
        passed, reasons = runner(sample)
        fired = not passed
        if sample["label"] == "planted":
            caught += int(fired)
        else:
            false_alarms += int(fired)
        rows.append({
            "id": sample["id"], "label": sample["label"], "subtlety": sample["subtlety"],
            "defect_class": sample["defect_class"], "defect": sample["defect"],
            "check_fired": fired, "reasons": reasons[:3],
        })

    sens, sens_lo, sens_hi = wilson(caught, len(planted))
    far, far_lo, far_hi = wilson(false_alarms, len(clean))

    by_subtlety = {}
    for tier in ("blatant", "moderate", "subtle"):
        tier_rows = [r for r in rows if r["label"] == "planted" and r["subtlety"] == tier]
        if tier_rows:
            hit = sum(r["check_fired"] for r in tier_rows)
            point, lo, hi = wilson(hit, len(tier_rows))
            by_subtlety[tier] = {"caught": hit, "n": len(tier_rows),
                                 "sensitivity": point, "wilson": [lo, hi]}

    missed = [r["id"] for r in rows if r["label"] == "planted" and not r["check_fired"]]
    fired_clean = [r["id"] for r in rows if r["label"] == "clean" and r["check_fired"]]
    return {
        "check_type": check_type,
        "n_samples": len(samples), "n_planted": len(planted), "n_clean": len(clean),
        "caught": caught, "false_alarms": false_alarms,
        "sensitivity": sens, "sensitivity_wilson": [sens_lo, sens_hi],
        "false_alarm_rate": far, "false_alarm_wilson": [far_lo, far_hi],
        "by_subtlety": by_subtlety, "missed": missed, "false_alarm_ids": fired_clean,
        "rows": rows,
    }


def fmt_pct(x: float) -> str:
    return f"{x * 100:.1f}%"


def render(header: dict, results: list[dict], thresholds: dict, verdicts: list[tuple]) -> str:
    lines = [
        "# Check-type measurement — g2_checks_catch_planted_defects",
        "",
        "Every number below comes from scripts/check_measure.py over the labelled sets in",
        "data/checks/. Thresholds are read from EVAL.md, never from this file.",
        "",
        "## Header (baseline identity)",
        "",
        "| field | value |",
        "| --- | --- |",
    ]
    for key in ("judge_model", "judge_agreement", "judge_agreement_floor", "rubric_version",
                "rubric_prompt_sha256_16", "sets_version", "assert_set_sha",
                "grounded_set_sha", "rubric_set_sha", "agreement_set_sha", "judge_calls",
                "not_run"):
        lines.append(f"| {key} | `{header.get(key)}` |")
    if header.get("not_run"):
        lines += [
            "",
            f"> **Incomplete run.** {', '.join(header['not_run'])} were NOT measured: no judge "
            "model is available, so there is no rate to report for them. The `assert` numbers "
            "below are real; the absent ones are absent, not zero. See BLOCKED.md.",
        ]
    lines += [
        "",
        "A change to any row above invalidates a stored baseline: the judge model, the rubric",
        "text and the labelled sets are all part of what the numbers mean (EVAL.md embedder rule).",
        "",
        "## Results",
        "",
        "| check | n | planted | sensitivity (95% Wilson) | clean | false alarms (95% Wilson) |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for r in results:
        lines.append(
            f"| {r['check_type']} | {r['n_samples']} | {r['caught']}/{r['n_planted']} | "
            f"{fmt_pct(r['sensitivity'])} [{fmt_pct(r['sensitivity_wilson'][0])}, "
            f"{fmt_pct(r['sensitivity_wilson'][1])}] | "
            f"{r['false_alarms']}/{r['n_clean']} | "
            f"{fmt_pct(r['false_alarm_rate'])} [{fmt_pct(r['false_alarm_wilson'][0])}, "
            f"{fmt_pct(r['false_alarm_wilson'][1])}] |"
        )
    lines += ["", "## Sensitivity by planted-defect subtlety", "",
              "| check | blatant | moderate | subtle |", "| --- | --- | --- | --- |"]
    for r in results:
        cells = []
        for tier in ("blatant", "moderate", "subtle"):
            t = r["by_subtlety"].get(tier)
            cells.append(f"{t['caught']}/{t['n']} ({fmt_pct(t['sensitivity'])})" if t else "—")
        lines.append(f"| {r['check_type']} | " + " | ".join(cells) + " |")

    lines += ["", "## Acceptance against EVAL.md", "",
              "| check | criterion | threshold | measured | verdict |",
              "| --- | --- | --- | --- | --- |"]
    for check_type, criterion, threshold, measured, ok in verdicts:
        lines.append(f"| {check_type} | {criterion} | {threshold} | {measured} | "
                     f"{'PASS' if ok else 'FAIL'} |")

    lines += ["", "## What each check missed", ""]
    for r in results:
        misses = r["missed"] or ["none"]
        alarms = r["false_alarm_ids"] or ["none"]
        lines.append(f"- **{r['check_type']}** — missed planted: {', '.join(misses)}; "
                     f"fired on clean: {', '.join(alarms)}")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    judge_model = os.environ.get("SEISMO_JUDGE_MODEL", "")
    key = os.environ.get("OPENROUTER_API_KEY", "")

    # `assert` needs no judge, so a missing judge does not stop it from being
    # measured for real. The two judge-backed types are then reported as NOT RUN
    # and the exit code is non-zero — a partial measurement is never a pass, and
    # it is never silently presented as a complete one.
    judge_available = bool(judge_model and key)
    if not judge_available:
        missing = "SEISMO_JUDGE_MODEL" if not judge_model else "OPENROUTER_API_KEY"
        print(f"check_measure: {missing} unset — measuring `assert` only. "
              "grounded and rubric will be reported as NOT RUN. This never defaults "
              "to a remembered model id and never invents a rate.")

    gateway = None
    if judge_available:
        from groundwork import BaseConfig, LLMGateway
        gateway = LLMGateway(BaseConfig(openrouter_api_key=key))

    thresholds = read_thresholds()
    assert_set, grounded_set, rubric_set = (load_set(t) for t in TYPES)
    agreement_set = json.loads(
        (SETS / f"judge_agreement_set.{VERSION}.json").read_text(encoding="utf-8"))

    calls = {"n": 0}

    def assert_runner(sample):
        outcome = run_assert_check(sample["output"], assert_set["policy"], sample["reference"])
        return outcome.passed, outcome.reasons

    def grounded_runner(sample):
        calls["n"] += 1
        outcome = run_grounded_check(gateway, judge_model, sample["output"],
                                     sample["reference"], grounded_set["years_tolerance"])
        return outcome.passed, outcome.reasons

    def rubric_runner(sample):
        calls["n"] += 1
        outcome = run_rubric_check(gateway, judge_model, sample["output"],
                                   rubric_set["pass_score"])
        return outcome.passed, outcome.reasons

    results = [measure("assert", assert_set["samples"], assert_runner)]
    not_run = []
    if judge_available:
        results.append(measure("grounded", grounded_set["samples"], grounded_runner))
        results.append(measure("rubric", rubric_set["samples"], rubric_runner))
    else:
        not_run = ["grounded", "rubric"]

    verdicts = []
    for r in results:
        t = thresholds[r["check_type"]]
        verdicts.append((r["check_type"], "sensitivity >= floor", t["min_sensitivity"],
                         fmt_pct(r["sensitivity"]), r["sensitivity"] >= t["min_sensitivity"]))
        verdicts.append((r["check_type"], "false-alarm rate <= ceiling", t["max_false_alarm"],
                         fmt_pct(r["false_alarm_rate"]),
                         r["false_alarm_rate"] <= t["max_false_alarm"]))
    for name in not_run:
        verdicts.append((name, "measured at all", "required", "NOT RUN — no judge model", False))

    header = {
        "judge_model": judge_model or "NOT SELECTED — see BLOCKED.md",
        "not_run": not_run,
        "judge_agreement": os.environ.get("SEISMO_JUDGE_AGREEMENT", "see check_selection.json"),
        "judge_agreement_floor": os.environ.get("SEISMO_JUDGE_AGREEMENT_FLOOR", "0.85"),
        "rubric_version": RUBRIC_VERSION,
        "rubric_prompt_sha256_16": hashlib.sha256(RUBRIC_TEXT.encode()).hexdigest()[:16],
        "sets_version": VERSION,
        "assert_set_sha": assert_set["content_sha256_16"],
        "grounded_set_sha": grounded_set["content_sha256_16"],
        "rubric_set_sha": rubric_set["content_sha256_16"],
        "agreement_set_sha": agreement_set["content_sha256_16"],
        "judge_calls": calls["n"],
    }

    REPORT_MD.write_text(render(header, results, thresholds, verdicts), encoding="utf-8")
    payload = {
        "header": header, "thresholds": thresholds,
        "results": [{k: v for k, v in r.items() if k != "rows"} for r in results],
        "verdicts": [
            {"check": c, "criterion": cr, "threshold": th, "measured": m, "pass": ok}
            for c, cr, th, m, ok in verdicts
        ],
        "rows": {r["check_type"]: r["rows"] for r in results},
    }
    REPORT_JSON.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    for r in results:
        print(f"{r['check_type']:<9} sensitivity={fmt_pct(r['sensitivity'])} "
              f"({r['caught']}/{r['n_planted']})  "
              f"false_alarm={fmt_pct(r['false_alarm_rate'])} "
              f"({r['false_alarms']}/{r['n_clean']})")
    failed = [v for v in verdicts if not v[4]]
    for check_type, criterion, threshold, measured, _ in failed:
        print(f"THRESHOLD MISS {check_type}: {criterion} {threshold}, measured {measured}")
    print(f"check_measure: {calls['n']} judge calls")
    print("MEASURE_JSON " + json.dumps({
        "header": header, "thresholds": thresholds,
        "results": [{k: v for k, v in r.items() if k not in ("rows",)} for r in results],
        "verdicts": payload["verdicts"], "judge_calls": calls["n"],
    }))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
