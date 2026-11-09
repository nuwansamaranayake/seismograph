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

## Check types: assert, grounded, rubric

Three check types run over labelled sets in `data/checks/`, 44 samples each, 22 clean and 22
with a planted defect at one of three subtlety tiers. `scripts/build_check_sets.py` is the
reviewable source of every sample and every planted defect; the JSON it freezes is what the
measurement reads. `scripts/check_measure.py` produces `check_report.md`.

Sensitivity is the share of planted defects the check fires on. The false-alarm rate is the
share of clean samples it fires on anyway. Both carry a 95% Wilson interval, and a rate over
zero samples raises rather than reporting 0%.

### Thresholds

Set before the first measurement and never moved to accommodate a result. A miss exits
non-zero and fails `g2_checks_catch_planted_defects`.

<!-- g2-thresholds:start -->

| check | min sensitivity | max false-alarm rate |
| --- | --- | --- |
| assert | 0.95 | 0.05 |
| grounded | 0.80 | 0.10 |
| rubric | 0.70 | 0.15 |

<!-- g2-thresholds:end -->

The three floors differ because the three checks are asked different questions. `assert` is
deterministic code applied to defect classes its own rules name, so anything below near-perfect
is a bug in the rules. `grounded` depends on a model reading a fact out of prose correctly, so
it inherits that model's extraction error. `rubric` asks for a judgement about tone and policy
where humans themselves disagree at the margins, and it is held to the loosest floor for that
reason — a rubric check is a smoke alarm, not a court.

### Limits, one per type

- **assert** — measures coverage of the defect classes its own rules name (schema, forbidden and
  required patterns, numeric tolerance, field equality) and says nothing about any defect with
  no lexical or structural signature; a fluent, well-formed, completely wrong reading passes it.
- **grounded** — measures only whether the prose agrees with the reference on the five chart
  facts it extracts, so it cannot see a defect in any claim outside those five fields, and its
  error floor is the judge model's extraction error, not the check's logic.
- **rubric** — measures policy compliance as one model reads the written rubric on one reading
  at temperature 0; its numbers move when the judge model, the rubric text, or the labelled set
  changes, which is why all three are hashed into every report header.

### Judge model

Never taken from memory. `scripts/judge_select.py` reads the live OpenRouter model list at run
time, filters to pinned, paid, structured-output-capable text models, ranks them cheapest-first
(price per token is the only size proxy the provider publishes), and walks that ranking until
one agrees with the human labels on `data/checks/judge_agreement_set.v1.json` at **>= 0.85**.
The first model to clear wins — the smallest adequate judge, not the best one. The agreement set
is disjoint from the three measured sets so that selection cannot inflate sensitivity. The
chosen id is written to `.env` as `SEISMO_JUDGE_MODEL` and into every report header.

## Status

The harness is real and the curve above is its current output, regenerated on every run.
`make eval` reproduces it byte-for-byte from a clean clone, and CI runs it as a required check.
