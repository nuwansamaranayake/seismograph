# Roadmap — Seismograph

Three phases, mirroring the MVP build path in the blueprint. Each phase maps to a GitHub Milestone;
the public project board tracks issues under it.

## Phase 1 — Useful in CI on day one
*Mirrors GitHub milestone `phase-1`.*

The deterministic spine plus the first invariant — the smallest thing a maintainer can adopt.

- Behavioral-contract YAML schema and a deterministic contract compiler that emits an experiment
  plan.
- Sampler: N runs × M configurations against a system-under-test adapter.
- Canonicalizer: normalize, embed, and reduce outputs to distributional metrics.
- Control charts with statistically derived limits; the first metamorphic invariant (paraphrase
  invariance) with its deterministic embedding-plus-NLI back-check.
- CLI report and the golden-defect suite: `make eval` reproduces the published report.

Exit: a maintainer adds a contract to a repo and CI fails on a paraphrase-driven decision flip.

## Phase 2 — Full instrument and the dashboard
*Mirrors GitHub milestone `phase-2`.*

**Status 2026-11-09: built on `feat/phase-2-dashboard`, version 0.4.0, not yet released.** Every
item below is implemented and tested. The exit's second half, "the gate runs as a GitHub check",
is wired (`action.yml`, `.github/workflows/gate.yml`) and proven locally by exit code. It has not
been observed on GitHub until this branch's first CI run.

- The full invariant set: irrelevance, order, monotonicity, and format stability.
- Outcome-mode clustering — surfacing the hidden second mode the averages conceal.
- Judge panel with human-anchor calibration and drift quarantine.
- **Next.js frontend:** the control-chart and mode-topology dashboard, on the portfolio's shared
  design system.
- GitHub Actions release-gate integration.

Exit: a team sees consistency trends and mode topology in a browser, and the gate runs as a GitHub
check on every pull request.

## Phase 3 — Attribution, monitoring, benchmarking
*Mirrors GitHub milestone `phase-3`.*

- Fault-attribution engine: controlled interventions (swap the retrieval snapshot, swap the model
  version, replay with tool results frozen) reporting per-component effect sizes.
- Scheduled production monitoring with explicit re-baselining discipline.
- ACI benchmarking across providers.
- Incident narrator: reports grounded in verified statistics only.

Exit: an alarm becomes a finding — "the flip rate moved with the retriever change, not the model
update" — with the evidence attached.
