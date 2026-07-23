# EVAL — Seismograph

## What "good" means

Seismograph's job is to measure whether an LLM application is a *stable* stochastic process. So it is
held to the standard it imposes: its own detectors must be accurate, sensitive, and quiet when
nothing is wrong. "Good" is not "the demo looked convincing" — it is measured behavior on systems
whose defects are known in advance.

## How `make eval` measures it

Seismograph evals itself against synthetic systems under test — mock endpoints with *programmable*
defects:

- drift injected on day K,
- a format flake at rate p,
- a planted second outcome mode,
- a seeded retriever fault for the attribution engine to find.

Because every defect is planted, the ground truth is known and the following are measurable exactly
rather than argued:

- **Detection latency** — how many run cycles after onset the control chart signals.
- **False-alarm rate** — spurious gate blocks on defect-free systems, using Western Electric rules
  and minimum-effect-size thresholds (not raw p-values) to resist alarm fatigue.
- **Sensitivity** — the smallest planted second-mode share reliably detected.
- **Attribution accuracy** — how often the intervention engine names the correct faulted component on
  the seeded-fault suite.

This golden-defect suite ships in the repo. `make eval` runs it and reproduces the published eval
report per release; the release is gated on those numbers, not on a green demo.

## Phase 1 acceptance thresholds (written before the harness, 2026-07-23)

The Phase 1 suite simulates monitored metric streams with a 30-point baseline window and defects
planted at known onset K, using fixed seeds and the deterministic `HashingEmbedder` so the run is
keyless, free, and byte-reproducible in CI. `scripts/eval.py` exits nonzero and prints the failing
row if any bound is missed.

| Metric | Definition | Bound |
|---|---|---|
| Detection latency, jump | points after K until first alarm, planted mean shift of at least 2 sigma | median <= 3 |
| Detection latency, drift | points after K until first alarm, gradual drift reaching 2 sigma by K+10 | median <= 10 |
| Sensitivity | planted defects (jumps, drifts, flake bursts) raising at least one alarm | >= 0.90 |
| False-alarm rate | alarms per point on defect-free streams (Western Electric rule 1 + run-of-8) | <= 0.01 |
| Format-flake detection | planted malformed-output bursts at p >= 0.10 flagged by the p-chart | >= 0.90 |
| Reproducibility | two consecutive `make eval` runs | identical reports |

Planted-second-mode sensitivity joins in Phase 2 (with mode clustering); seeded-fault attribution
accuracy joins in Phase 3 (with the intervention engine). Each gets its bounds written before its
code, as here.

Why a deterministic embedder here: this suite measures the statistical machinery (charts, rules,
latency), not embedding quality. The real embedding path is exercised by the metamorphic
back-check and development smoke. Embedder selection is always an explicit, typed choice — never a
fallback (Standard 3).

## Status

The harness is real as of Phase 1: `scripts/eval.py` runs the golden-defect suite against the
table above and exits nonzero on any miss. First published run (2026-07-23, also in
`eval_report.md`): jump latency median 0.0, drift 1.0, sensitivity 1.0, false alarms 0.0,
flake detection 1.0, report byte-reproducible across consecutive runs. The CI eval job is a
required check ("eval (required)"). Phase 2/3 rows get their bounds written before their
code, as these were.
