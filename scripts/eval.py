"""Eval harness: publish the operating curve, then gate on it.

Deterministic and keyless (fixed seeds, hashing embedder, no network). Writes:
  eval_report.md   the curve, the misses, the null-cell false alarm rate
  eval_curve.svg   the same curve as a committed chart
  eval_baseline.json  the embedder identity and healthy-process parameters

A silent embedder change corrupts every baseline, so the stored identity is compared against
the live one and a mismatch fails loudly rather than quietly re-baselining.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.engine.golden import (  # noqa: E402
    HEALTHY_FLIP_P, N_SAMPLES, acceptance, embedder_identity, run_suite, thresholds_met,
)

ROOT = Path(__file__).resolve().parent.parent
REPORT = ROOT / "eval_report.md"
CURVE = ROOT / "eval_curve.svg"
BASELINE = ROOT / "eval_baseline.json"


def check_baseline() -> str:
    """Compare the live measurement identity against the stored baseline. Fail on drift."""
    live = {"embedder": embedder_identity(),
            "healthy_flip_p": HEALTHY_FLIP_P,
            "n_samples": N_SAMPLES}
    if BASELINE.exists():
        stored = json.loads(BASELINE.read_text(encoding="utf-8"))
        if stored != live:
            diffs = [f"{k}: baseline={stored.get(k)!r} now={live[k]!r}"
                     for k in live if stored.get(k) != live[k]]
            print("EVAL FAILED: measurement identity does not match the stored baseline. "
                  "Re-baseline explicitly (delete eval_baseline.json) rather than letting "
                  "the curve drift silently.\n  " + "\n  ".join(diffs), file=sys.stderr)
            sys.exit(1)
        return "matches stored baseline"
    BASELINE.write_text(json.dumps(live, indent=2, sort_keys=True) + "\n",
                        encoding="utf-8", newline="\n")
    return "stored (first run)"


def main() -> None:
    baseline_state = check_baseline()
    report = run_suite()

    REPORT.write_text(report.render(), encoding="utf-8", newline="\n")
    CURVE.write_text(report.svg, encoding="utf-8", newline="\n")
    print(report.render())
    print(f"baseline: {baseline_state}\n")

    print("| acceptance check | observed | pass |")
    print("|---|---|---|")
    for name, observed, ok in acceptance(report):
        print(f"| {name} | {observed} | {'PASS' if ok else 'FAIL'} |")

    if not thresholds_met(report):
        print("\nEVAL FAILED: an acceptance bound was missed (see the table above)",
              file=sys.stderr)
        sys.exit(1)
    print("\nEVAL OK")


if __name__ == "__main__":
    main()
