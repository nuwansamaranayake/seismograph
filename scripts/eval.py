"""Eval harness: the golden-defect suite against the EVAL.md thresholds.

Exits nonzero and prints the failing rows if any bound is missed. Deterministic: fixed
seeds, HashingEmbedder, no network. The report is written to eval_report.md so two
consecutive runs can be compared byte-for-byte (the reproducibility bound).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.engine.golden import run_suite, thresholds_met  # noqa: E402

REPORT = Path(__file__).resolve().parent.parent / "eval_report.md"


def main() -> None:
    report = run_suite(n_per_kind=20)
    text = report.render()
    REPORT.write_text(text, encoding="utf-8", newline="\n")
    print(text)
    if not thresholds_met(report):
        print("EVAL FAILED: at least one threshold missed (see rows above)", file=sys.stderr)
        sys.exit(1)
    print("EVAL OK")


if __name__ == "__main__":
    main()
