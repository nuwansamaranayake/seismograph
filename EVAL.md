# EVAL — Seismograph

## What "good" means

Seismograph's job is to measure whether an LLM application is a *stable* stochastic process. So it is
held to the standard it imposes: its own detectors must be accurate, sensitive, and quiet when
nothing is wrong. "Good" is not "the demo looked convincing" — it is measured behavior on systems
whose defects are known in advance.

## Published limits

This sentence is what the root page publishes, verbatim. The gate fails if the page and this block drift apart.

<!-- LIMITS -->
Seismograph detects an abrupt mean shift of 1 sigma or larger in the monitored statistic within a median of 5 monitored points (40 samples per point) at a false alarm rate of 0.017 per point, and it misses below that: a 0.5 sigma shift is caught about half the time (0.50, 95% CI 0.33-0.67) and a 0.25 sigma shift about two times in five (0.43, 95% CI 0.27-0.61).
<!-- /LIMITS -->


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

## What this instrument detects, and what it misses

Seismograph detects an abrupt mean shift of **1 sigma or larger** in the monitored statistic within a **median of 5 monitored points** (40 samples per point) at a **false alarm rate of 0.017 per point**, and it misses below that: a 0.5 sigma shift is caught about half the time (0.50, 95% CI 0.33-0.67) and a 0.25 sigma shift about two times in five (0.43, 95% CI 0.27-0.61).

The full operating curve, 30 runs per cell with 95% Wilson intervals, is published in
[eval_report.md](eval_report.md) and charted in [eval_curve.svg](eval_curve.svg).

## How the curve is built

Defects are sized in units of the healthy process's own standard deviation, which is analytic
for the monitored statistic (a flip rate over n Bernoulli draws):
`sigma = sqrt(p0 * (1 - p0) / n)`. A "k sigma" cell plants a process whose mean sits k sigma
above healthy. The sweep runs from 0.25 sigma, far below what a 3-sigma chart can see, up to
3 sigma, and includes matched null cells with no planted defect so the false alarm rate is
measured rather than assumed. Gradual ramps and format-flake rates from 1% to 20% are swept
the same way.

Publishing the misses is the point. A detector and its benchmark written by the same hand will
score perfectly whenever the planted defects are easy; that scorecard only means something if
it contains failures at the magnitudes where failure is expected.

## Acceptance bounds (what gates a release)

Bounds are stated on the parts of the curve an instrument must get right, not on every cell.
Demanding detection at 0.25 sigma would be demanding the impossible, and demanding zero false
alarms would be demanding a chart that never speaks.

| Check | Bound | Observed |
|---|---|---|
| Sensitivity at 3 sigma | >= 0.90 | 1.00 |
| Sensitivity at 20% format flake | >= 0.90 | 1.00 |
| False alarm rate on null cells | <= 0.03 | 0.0167 (95% CI 0.0108-0.0256) |
| Sensitivity non-decreasing in magnitude | monotone within 0.10 | 0.43, 0.50, 0.97, 1.00, 1.00, 1.00 |
| Every cell computed from a non-zero sample count | required | 18,000 monitored points |
| Report and chart byte-reproducible | required | verified across consecutive runs |
| Measurement identity matches stored baseline | required | `hashing/dim=256/v1` |

A missed bound exits non-zero and fails CI. The embedder identity is recorded in every report
header and compared against `eval_baseline.json`, because a silent embedder change corrupts
every baseline: re-baselining must be explicit.

## Key-gated back-check (not a required check)

`scripts/eval_llm.py` runs the metamorphic paraphrase back-check against the real gateway:
**53 of 54 variants accepted, 0.98 (95% CI 0.90-1.00)** across nine statement types (question,
numeric, negation, policy, conditional, instruction, multi-clause, terse, formal), plus planted
negative controls that must be rejected. It exits 2 loudly without a key rather than skipping
silently. Raising it from four variants to fifty-four is what exposed the numeric blind spot
recorded in FAILURES.md.

## Status

The harness is real and the curve above is its current output, regenerated on every run.
`make eval` reproduces it byte-for-byte from a clean clone, and CI runs it as a required check.
