# Changelog

All notable changes to Seismograph are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added — Phase 1 core loop (branch `phase-1`)
- Behavioral contract DSL (YAML -> validated models -> deterministic content-hashed
  experiment plan). Declaring any perturbation is legal; executing one without a generator
  raises loudly.
- Synthetic programmable-defect SUTs (jump, drift, format flake), seeded replayable sampler,
  canonicalizer (flip rate, pairwise jaccard, malformed rate, semantic variance), X-chart
  (Western Electric rule 1 + run-of-8) and p-chart with binomial limits.
- Real golden-defect eval harness enforcing the pre-written EVAL.md bounds; observed: jump
  latency median 0.0 (<=3), drift 1.0 (<=10), sensitivity 1.0 (>=0.90), false alarms 0.0
  (<=0.01), flake detection 1.0 (>=0.90), byte-reproducible report (eval_report.md).
- Persisted contract -> run -> report API with bearer auth; alembic 0002 real schema
  (8 app tables; MIGRATION OK: 9 tables observed); CLI report that exits nonzero on a
  blocking gate.
- Metamorphic paraphrase invariant: gateway-generated variants, deterministic
  embedding-cosine back-check; rejected variants kept for the failure gallery. Real path
  observed 4/4 accepted.

### Changed
- CI eval job is now REQUIRED ("eval (required)"): a missed bound fails the build.
- Smoke test now exercises the full business loop, not just health + fixture.

### Changed
- Dependency on `aignite-groundwork` switched from an editable path source to a pinned git
  dependency (`git+https://github.com/nuwansamaranayake/groundwork@v0.1.0`) so standalone clones and CI resolve
  it without a sibling checkout. PyPI publication planned at first release.
- `scripts/check_migrations.py` now uses `DATABASE_URL` with the declared psycopg v3 driver
  unmodified, fixing a clean-machine `make migrate` failure (see FAILURES.md FAIL-0002).
- README truth pass: scaffold status block, `(the design)` heading, "What exists today (verified)"
  section, scoped/dated novelty, dual-path Quickstart, em-dash sweep.
- CI: Python matrix (3.12, 3.13); eval job labeled "eval (Phase 1 pending)".

### Added
- `CODE_OF_CONDUCT.md` (Contributor Covenant 2.1) and a SECURITY.md vulnerability-reporting policy.

## [0.1.0] - 2026-07-21
### Added
- Engineering harness scaffold: governed doc set, config guard, verification gates,
  smoke test against a real business endpoint, migration-count check, CI pipeline,
  and a synthetic dataset so the demo runs with zero external keys.
