# 2. The LLM senses, deterministic code decides

Date: 2026-07-21

## Status

Accepted

## Context

Seismograph is an eval instrument whose credibility depends on its verdicts being reproducible and
defensible. It also uses an LLM in two places that are, by nature, non-deterministic: generating
metamorphic input variants, and drafting incident narration. If those non-deterministic steps were
allowed to influence a number, a control limit, or a ship/no-ship decision, the instrument would
inherit the very drift it exists to measure — an eval tool that itself changes behavior on a silent
model update is worthless.

The portfolio thesis states the rule: the LLM is a sensor, not a judge. This ADR fixes where that
boundary sits for Seismograph, grounded in the Deterministic vs Non-Deterministic split in the app
chapter.

## Decision

We draw a hard line between sensing and deciding.

**The LLM senses** (non-deterministic, always back-checked):

- *Metamorphic variant generation* — the LLM proposes paraphrases and perturbations of seed probes.
  No proposed variant enters the probe bank until a deterministic back-check (embedding similarity
  plus NLI entailment against the original) verifies it preserves meaning. Perception proposes,
  verification disposes.
- *Judge-panel verdicts* — treated as a drifting instrument, anchored to a human-labeled set and
  quarantined when agreement decays past threshold.
- *Incident narration* — prose grounded in already-verified statistics only; it may describe the
  numbers, never produce them.

**Deterministic code decides and computes** (reproducible, the source of every number):

- Contract compilation, experiment planning, and seeds.
- Canonicalization, embedding, and outcome-mode clustering.
- Control charts, KS tests, mode entropy, and the AI Capability Index.
- Judge-vs-anchor agreement scoring, intervention scheduling, and effect-size estimation.
- Release gates and the cost ledger.

The system under test is likewise untrusted: its output is data to be measured, never an instruction
to be followed.

## Consequences

- Re-running the deterministic pipeline over the same runs yields the same verdict, so a gate
  decision is auditable and a reviewer can reconstruct it.
- Every LLM output crosses a deterministic checkpoint before it can affect a result; a bad variant or
  a drifted judge is caught, logged to the failure gallery, and quarantined rather than silently
  trusted.
- The instrument does not inherit provider drift in its own decisions — which is the entire point of
  an eval gate.
- Cost: distribution-level sampling and back-checks add token spend and latency. This is accepted and
  bounded by the planner's budget (see the chapter's "cost blowout" failure mode).
