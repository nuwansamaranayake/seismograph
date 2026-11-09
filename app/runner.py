"""Run a suite against a target and decide, deterministically, whether it passed.

The shape of a run (docs/gates-spec.md g4):

    select cases for the profile -> call the target once per repeat
    -> every repeat must agree (determinism)
    -> every layer's check runs over the output
    -> compare the per-layer verdicts against the committed baseline (drift)

Three separate failure kinds, kept separate on purpose because the CLI's exit
code and the alert subject distinguish them:

  failures    a check found a defect, or a target call errored
  drift       a layer that passed in the baseline fails now
  incomplete  a declared layer could not run at all (e.g. a judge layer with no
              judge model configured). An eval that skipped a layer must never
              look like an eval that passed it.

Nothing here reaches for a default when configuration is missing, and no layer
is silently dropped.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path

from .checks import RUBRIC_VERSION, run_assert_check, run_grounded_check, run_rubric_check
from .suite import Case, Layer, Profile, Suite

GROUNDED_YEARS_TOLERANCE = 1.0

# Header keys a baseline is NOT identified by. The baseline records per-case
# verdicts, so which cases today's profile happened to select, and whether the
# run also wrote to Postgres, cannot make it a different baseline. Everything
# else — suite version, suite digest, target, judge model, rubric version —
# must match, or the comparison is meaningless (EVAL.md).
BASELINE_VOLATILE = ("profile", "stored_in_postgres")


@dataclass(frozen=True)
class LayerOutcome:
    case_id: str
    layer: str
    check_type: str
    passed: bool
    reasons: list[str] = field(default_factory=list)

    @property
    def key(self) -> str:
        return f"{self.case_id}::{self.layer}"


@dataclass
class RunResult:
    suite: str
    profile: str
    target_id: str
    header: dict
    outcomes: list[LayerOutcome] = field(default_factory=list)
    incomplete: list[str] = field(default_factory=list)
    drifted: list[str] = field(default_factory=list)
    unbaselined: list[str] = field(default_factory=list)
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @property
    def failures(self) -> list[LayerOutcome]:
        return [o for o in self.outcomes if not o.passed]

    @property
    def verdicts(self) -> dict[str, bool]:
        return {o.key: o.passed for o in self.outcomes}


def header_for(suite: Suite, profile: Profile, target_id: str, judge_model: str | None,
               stored: bool) -> dict:
    """The report header. A baseline is only comparable to a run with the same
    header — EVAL.md's baseline-header rule, which exists so a changed judge or
    rubric can never be read as a changed system."""
    return {
        "suite": suite.name,
        "suite_version": suite.version,
        "suite_sha256_16": suite.content_sha256_16(),
        "profile": profile.name,
        "target_id": target_id,
        "judge_model": judge_model,
        "rubric_version": RUBRIC_VERSION if judge_model else None,
        "prompt_hash": None,
        "stored_in_postgres": stored,
    }


def _run_layer(layer: Layer, output: dict, case: Case, judge, judge_model: str | None):
    """Run one layer over one output. Returns (outcome | None, incomplete_reason | None)."""
    text = json.dumps(output, ensure_ascii=False)
    if layer.check == "assert":
        result = run_assert_check(text, layer.policy, case.reference)
    elif layer.check in ("grounded", "rubric"):
        if judge is None or not judge_model:
            return None, (
                f"{case.id}::{layer.name}: {layer.check} layer needs a judge model; "
                "SEISMO_JUDGE_MODEL is unset"
            )
        prose = layer.policy.get("prose_field")
        reading = output.get(prose, text) if prose else text
        if layer.check == "grounded":
            result = run_grounded_check(
                judge, judge_model, reading, case.reference, GROUNDED_YEARS_TOLERANCE
            )
        else:
            result = run_rubric_check(judge, judge_model, reading)
    else:
        return None, f"{case.id}::{layer.name}: unknown check type {layer.check!r}"
    return (
        LayerOutcome(case.id, layer.name, layer.check, result.passed, list(result.reasons)),
        None,
    )


def run_suite(suite: Suite, target, profile: Profile, *, on: date, baseline: dict | None = None,
              judge=None, judge_model: str | None = None, session=None) -> RunResult:
    """Call the target for every selected case and check every declared layer.

    `session`, when given, persists each call record (app/targets.record_call).
    It is passed explicitly rather than inferred, so a run never half-stores.
    """
    from .targets import record_call  # local import: keeps the DB optional at import time

    # The target object owns its id: a fixture target and production Kalika are
    # different targets and must never share a baseline.
    target_id = getattr(target, "target_id", suite.target_id)
    result = RunResult(
        suite=suite.name,
        profile=profile.name,
        target_id=target_id,
        header=header_for(suite, profile, target_id, judge_model, stored=session is not None),
    )
    baseline_verdicts = (baseline or {}).get("verdicts", {})

    for case in suite.select(profile, on):
        outputs = []
        error = None
        for _ in range(profile.repeats):
            record = target.call(body=case.request, json_path=suite.json_path)
            if session is not None:
                record_call(session, record)
            if record.error:
                error = record.error
                break
            outputs.append(record.raw_response)

        if error is not None:
            result.outcomes.append(
                LayerOutcome(case.id, "target", "call", False, [f"target call failed: {error}"])
            )
            continue

        if len(outputs) > 1 and any(o != outputs[0] for o in outputs[1:]):
            result.outcomes.append(
                LayerOutcome(case.id, "determinism", "assert", False,
                             [f"{profile.repeats} repeats did not produce identical output"])
            )
        elif len(outputs) > 1:
            result.outcomes.append(LayerOutcome(case.id, "determinism", "assert", True))

        for layer in suite.layers:
            outcome, incomplete = _run_layer(layer, outputs[0], case, judge, judge_model)
            if incomplete:
                result.incomplete.append(incomplete)
            else:
                result.outcomes.append(outcome)

    for outcome in result.outcomes:
        was = baseline_verdicts.get(outcome.key)
        if was is None:
            result.unbaselined.append(outcome.key)
        elif was and not outcome.passed:
            result.drifted.append(outcome.key)

    return result


def load_baseline(path: Path, header: dict) -> dict | None:
    """Read the committed baseline, refusing one written under a different header.

    A silent header mismatch would let a judge or rubric swap masquerade as a
    drifting system, so it raises instead (EVAL.md).
    """
    if not path.exists():
        return None
    baseline = json.loads(path.read_text(encoding="utf-8"))
    stored = baseline.get("header", {})
    differing = [k for k, v in header.items() if k not in BASELINE_VOLATILE and stored.get(k) != v]
    if differing:
        raise RuntimeError(
            f"baseline {path.name} header mismatch on {differing}: "
            f"baseline={ {k: stored.get(k) for k in differing} } run={ {k: header[k] for k in differing} }"
        )
    return baseline


def write_baseline(path: Path, result: RunResult) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "header": {k: v for k, v in result.header.items() if k not in BASELINE_VOLATILE},
        "recorded_at": result.started_at.isoformat(),
        "verdicts": result.verdicts,
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def report_markdown(result: RunResult) -> str:
    lines = [
        f"# Seismograph suite run — {result.suite} / {result.profile}",
        "",
        "| header | value |",
        "|---|---|",
        *[f"| {k} | `{v}` |" for k, v in result.header.items()],
        f"| started_at | `{result.started_at.isoformat()}` |",
        "",
        f"checks run: {len(result.outcomes)} | failed: {len(result.failures)} | "
        f"drifted: {len(result.drifted)} | incomplete: {len(result.incomplete)}",
        "",
        "| case | layer | check | verdict | reasons |",
        "|---|---|---|---|---|",
    ]
    for o in result.outcomes:
        reasons = "; ".join(o.reasons).replace("|", "\\|") or "-"
        lines.append(
            f"| {o.case_id} | {o.layer} | {o.check_type} | "
            f"{'PASS' if o.passed else 'FAIL'} | {reasons} |"
        )
    if result.drifted:
        lines += ["", "## drift vs baseline", *[f"- {k}" for k in result.drifted]]
    if result.incomplete:
        lines += ["", "## incomplete layers", *[f"- {r}" for r in result.incomplete]]
    if result.unbaselined:
        lines += ["", "## not in baseline", *[f"- {k}" for k in result.unbaselined]]
    return "\n".join(lines) + "\n"
