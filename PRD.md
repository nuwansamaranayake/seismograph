# PRD — Seismograph

## Users

- **AI product engineer** shipping an LLM feature to production, who needs a release gate that
  catches behavioral regressions the way unit tests catch functional ones.
- **Open-source maintainer** who wants CI to fail when a dependency, model, or prompt change silently
  shifts an AI feature's behavior.
- **AI PM / eng lead** who must define "good" for a probabilistic system and defend a ship/no-ship
  decision with evidence rather than vibes.
- **On-call engineer** triaging a "the vibes changed" report who needs to know whether the model
  update, the retriever, or the prompt moved the metric.

## Jobs-to-be-done

- Declare, in versioned YAML beside the prompt, what must not vary and by how much.
- Measure consistency as a distribution (N runs × M configs), not a single-sample score.
- Surface a hidden second outcome mode, and pin the onset date of a silent upstream change.
- Attribute a broken contract to a specific component under controlled replay.
- Block a CI build when a feature falls below its declared capability tolerance, with the evidence
  attached to the failure.

## Non-goals

Seismograph deliberately does not:

- Replace tracing, prompt playgrounds, or dataset runners. It *consumes* traces; it is not another
  observability suite.
- Make single-sample answer quality its headline. Quality scoring exists only as a calibrated,
  quarantinable input, never the product.
- Let the LLM decide anything consequential. The LLM senses (proposes variants, drafts narration);
  deterministic code computes every metric, every control limit, and every gate decision.
- Claim causal proof from production data. Fault attribution is scoped honestly as attribution under
  controlled replay.
- Author ground-truth golden answers. Metamorphic invariants exist precisely to avoid that cost.

## Novelty (scoped)

Among the eval tools we reviewed as of July 2026, single-sample quality scoring is the headline and
measuring the *stability* of a stochastic process is at most a footnote. Seismograph's scoped bet is
to make that stability its center: behavioral contracts as code, manufacturing-grade capability math
(Cp/Cpk-style), ground-truth-free metamorphic invariants, component-level fault attribution under
controlled replay, and a self-calibrating judge, delivered as one CI workflow. This is a novel
combination and emphasis, not a claim that any single technique is unprecedented.

## Success metrics (targets, not yet measured)

Seismograph evals itself against synthetic systems under test carrying *planted* defects (drift
injected on day K, a format flake at rate p, a planted second outcome mode, a seeded retriever
fault). Because the defects are known, these are measurable exactly. Phase-1 targets:

- **Detection latency** — flag an injected drift within a small, declared number of run cycles of its
  onset.
- **False-alarm rate** — hold spurious gate blocks under a low declared bound on defect-free systems
  (Western Electric rules and minimum-effect-size thresholds, not raw p-values).
- **Sensitivity** — reliably detect a planted second outcome mode above a declared share.
- **Attribution accuracy** — name the correct faulted component on the seeded-fault suite above a
  declared rate.

These are acceptance thresholds `make eval` will enforce (see EVAL.md). The harness raises
`NotImplementedError` until Phase 1, so none of the above is a claimed result yet.
