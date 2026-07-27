# Changelog

All notable changes to Seismograph are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Security
- Business read endpoints (GET /api/v1/reports/{contract}) now require the same bearer token as writes. They
  previously served real production data to unauthenticated callers (FAILURES FAIL-0007).

## [0.2.1] - 2026-07-23

### Fixed — adversarial review wave (12 findings; see FAILURES.md FAIL-0006)
- Zero-cell runs no longer persist a `pass` gate decision over zero measurements: the API
  returns 422 and the CLI exits 2 when a contract compiles to no executable plan cells.
- Malformed output now gates the run directly: `GatePolicy.max_malformed_rate` (default
  0.0) blocks any cell whose malformed rate exceeds it — previously 100% malformed output
  passed as healthy because unparsed samples vanished from the flip rate.
- Declared `jaccard_at_least` thresholds are now enforced at the gate (API and CLI); they
  were previously validated at parse time and never read again.
- Production startup refuses an empty `SMOKE_TEST_TOKEN` outside development
  (`app.main.require_production_auth`): auth-off is a development-only convenience.
- Golden-defect eval recalibrated to a genuinely noisy healthy baseline (flip probability
  0.04, n=40), defects sized ~4-7 sigma, run-of-8 signals once per run; the false-alarm
  bound is revised 0.01 -> 0.03 with rationale in EVAL.md (the old bound was attainable
  only while false alarms were structurally impossible).
- Metamorphic back-check rejects near-copies on similarity alone: a punctuation-only edit
  at cosine 1.0 was previously accepted because it failed exact string equality.
- Concurrent duplicate contract registrations now return the documented 409 (IntegrityError
  from the unique index is translated instead of surfacing as a 500).
- Migration 0002 is frozen as explicit DDL — it no longer applies whatever the live
  `app.db.metadata` currently says, so schema changes force a new numbered revision.
- `scripts/check_migrations.py` fails loud when `EXPECTED_TABLE_COUNT` is unset (it
  previously skipped the assertion and printed MIGRATION OK); the Dockerfile bakes
  `EXPECTED_TABLE_COUNT=9` so a bare `docker run` still asserts Standard 4.
- `scripts/gate.py` injects the resolved smoke token into the spawned server's environment,
  so the gate always exercises the bearer path with a matching token.
- CI test job installs groundwork from the ref pyproject pins and the `||` fallbacks that
  swallowed dependency-resolution failures are removed.
- README quickstart corrected: smoke token matches `.env.example` and the full smoke is
  documented as requiring the migrated compose stack.
- Added `.dockerignore` so `.git`, `.env` (which holds a live key locally), caches, and
  loop state are never baked into images.

## [0.2.0] - 2026-07-23

### Added — Phase 1 core loop
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
