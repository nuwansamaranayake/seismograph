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

## Status

The four measures above are **targets** the Phase-1 harness will enforce — not achieved
measurements. The current harness in `scripts/eval.py` raises
`NotImplementedError("eval harness lands in Phase 1")` on purpose: an eval that passes vacuously is
worse than one that fails loudly. Concrete numeric thresholds and the first published report land
with the Phase-1 golden-defect suite, each stated as a pass/fail acceptance bound *before* the code
that has to clear it — the same discipline this tool asks of its users.
