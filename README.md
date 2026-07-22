# Seismograph

> **Status: scaffold (v0.1).** The engineering harness is built and verified: live smoke test,
> fail-loud guards, migration checks, CI. The architecture described below is the design being
> built; Phase 1 is in progress. [ROADMAP.md](ROADMAP.md) shows what exists today versus what
> is next.

**Statistical process control for AI systems.** Everyone else asks "was this answer good?"
Seismograph asks "is this system stable?", and detects the silent earthquakes (model updates,
prompt edits, dependency drift) that change your app's behavior before your users do.

## What it is

Seismograph is an open-source eval instrument for teams shipping LLM features. Incumbent platforms
center tracing, prompt playgrounds, golden datasets, and LLM-as-judge scoring: single-sample
verdicts on quality. Seismograph centers the question they treat as a footnote: *how consistent is
my AI application, how is that trending, and did anything upstream silently change its behavior this
week?* It treats an LLM application the way a manufacturing engineer treats a production line: as a
stochastic process whose output is a distribution, not a point, and applies decades of industrial
process-control math to it.

Being open source is part of the thesis: teams are rightly wary of piping production traces into a
vendor, and an eval gate belongs inside your CI, not behind someone's meter.

## How it works (the design)

1. **Behavioral contracts as code.** A team declares, in versioned YAML, what must not vary, what
   may vary, and how much variation is tolerable. A deterministic compiler turns each contract into
   an experiment plan. Contracts live in the target repo, version with the prompts they protect, and
   fail builds.
2. **Sample distributions, not points.** For every probe the system under test is run N times across
   M configurations. Outputs are canonicalized, embedded, and clustered into *outcome modes*,
   because the dangerous failure is not noise, it is a hidden second mode the averages conceal.
   Metrics plot onto control charts with statistically derived limits; the headline is the **AI
   Capability Index (ACI)**, a Cp/Cpk-style capability score per feature against its contract.
3. **Metamorphic invariants replace golden answers.** You do not need the right answer to know
   paraphrase, irrelevance, order, and format invariance must hold. An LLM proposes input variants; a
   deterministic back-check (embedding similarity plus NLI entailment) verifies each before it enters
   the probe bank. Perception proposes, verification disposes.
4. **The judge is on trial too.** Every LLM judge is anchored against a small human-labeled set and
   continuously recalibrated. When agreement decays past threshold, that judge's verdicts are
   quarantined and flagged. The measuring instrument gets measured.

## What exists today (verified)

This scaffold's doctrine is already enforced, not promised. Three checks you can run in five minutes:

1. `python scripts/smoke_test.py` against a running instance: hits real endpoints and asserts
   non-empty, schema-valid data. Passes.
2. Set `APP_ENV=production` and call `/api/v1/demo`: returns 503, because fixture data outside
   development is forbidden by code, not by convention.
3. `python scripts/eval.py`: raises loudly instead of passing vacuously. An eval that cannot
   fail is theater; the real harness lands in Phase 1.

## The unique bet

Existing tools evaluate single samples against quality criteria (the tools we reviewed as of July
2026). Seismograph's bet is that the value lives elsewhere: an open-source instrument for measuring
the *stability* of a stochastic process, contracts as code, manufacturing-grade math,
ground-truth-free invariants, component-level fault attribution, and a self-calibrating judge, as one
CI workflow. "Accuracy 87%" demos better than "Cpk 1.1", right up until the first silent model update
burns you.

## Quickstart (local, zero external keys)

### Standalone clone

```bash
python -m venv .venv
source .venv/bin/activate         # POSIX     (.venv\Scripts\activate on Windows)
pip install -e .[dev]             # groundwork resolves from GitHub automatically
cp .env.example .env              # POSIX     (copy .env.example .env on Windows)
uvicorn app.main:app --reload
```

### Developing the whole portfolio (sibling checkout, editable)

```bash
git clone https://github.com/nuwansamaranayake/groundwork ../groundwork
pip install -e ../groundwork
pip install -e .[dev]
```

Then, in another shell:

```bash
export API_PORT=8000 SMOKE_TEST_TOKEN=dev && python scripts/smoke_test.py   # POSIX -> SMOKE OK
set API_PORT=8000 && set SMOKE_TEST_TOKEN=dev && python scripts/smoke_test.py  # Windows
```

The `/api/v1/demo` endpoint serves the synthetic dataset in `data/synthetic/`: no OpenRouter key, Postgres, or Redis is needed to see the app respond. Those are required only for Phase 1 features (real extraction, persistence, migrations).

## Demo

A recorded walkthrough, the policy-assistant "silent earthquake" scenario (a feature that passes a
conventional eval while flipping refund decisions under harmless paraphrases), lands as a GIF here
in Phase 2, alongside the Next.js dashboard. Until then, `/api/v1/demo` is the demo surface.

## Doctrine

The operating rules this repo is built and reviewed against, fail loud, smoke-test real endpoints,
no silent fallbacks, live in [DOCTRINE.md](DOCTRINE.md).
