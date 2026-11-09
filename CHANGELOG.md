# Changelog

All notable changes to Seismograph are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added — Phase 2: the full instrument and the dashboard (0.4.0, 2026-11-09)
- **Full invariant set.** Irrelevance, order and format perturbations are generated
  deterministically (`app/engine/perturb.py`). Monotonicity runs over a probe `ladder` with
  a declared `order`. A contract that declares a perturbation a probe cannot run under is
  refused at registration with the probe named.
- **Perturbed cells compare with the seed.** A metamorphic cell is judged against the modal
  answer to the unperturbed input, so a consistent wrong answer no longer agrees with itself
  into a pass (FAIL-0012).
- **Outcome modes** (`app/engine/modes.py`): signatures over the invariant fields, pooled over
  a 12 run window, with a Wilson 95% lower bound on the second mode's share. Optional gate
  `max_second_mode_share`.
- **Judge panel** (`app/engine/judges.py`): agreement with labelled anchors (interval and
  kappa), quarantine on the 0.8 floor or on p-chart drift, and a panel verdict that returns no
  label on a tie or without a quorum.
- **One gate executor** (`app/engine/execute.py`) used by the API, `seismo run` and the new
  `seismo gate`. Gate reasons are stored and stated as percentages.
- **`seismo gate`** and a composite GitHub Action (`action.yml`, `.github/workflows/gate.yml`).
  Exit 0 pass, 1 block, 2 cannot evaluate. A second CI job requires exit 1 on a planted defect.
- **Read API** for the dashboard: `/overview`, `/contracts`, `/contracts/{name}`, `/runs/{id}`,
  `/suts`, `/probes/variants`, `/judges/calibration`, `/judges/panel`, `/golden`. `contracts.md`
  is diffed against `/openapi.json` by a test.
- **Dashboard** (`web/`): Next.js 15 static export served by FastAPI from `WEB_DIR`. Overview,
  contracts, contract detail, run detail, judge panel, golden sets, guide. `/llms.txt` and
  JSON-LD are generated from `EVAL.md`.
- **Guide**: `/guide/` in the app and `docs/guide/seismograph-guide.html`, built by
  `scripts/build_guide.py` from `EVAL.md` and `eval_report.md`. Screenshots are recorded by
  `scripts/seed_demo.py` (simulators only, fixed seeds).
- **Quality gate** (`scripts/quality.py`): nine measured components, each at or above 96.
  Lint ruleset widened to B, I, UP, SIM. mypy is clean on `app/`.
- Ten built-in simulators, each with one planted defect, described at `/api/v1/suts`.

### Changed
- Migration `0004_modes_and_judges`: `outcome_modes`, `judge_calibrations`. 12 tables.
  `EXPECTED_TABLE_COUNT` 10 to 12 in `.env.example` and the `Dockerfile`. **Deploy note:** the
  host `.env` and `portfolio-ops` (`estate_smoke.py`, `vps_prepare.sh`) must change with it.
- The Dockerfile is two stage: node builds the dashboard, the Python image serves it.
- `seismo run --contract` measures every executable cell. It ran `repeat_run` cells only
  (FAIL-0014).

### Fixed
- `seismo run --suite` with `SEISMO_TARGET_ADAPTER=mcp` raised `AttributeError`: the runner
  calls `target.call()`, which `McpTarget` did not have (FAIL-0013).
- The Kalika suite digest depended on checkout line endings. A CRLF checkout and an LF runner
  now agree, and the 15 computed cases have a matching fixture baseline.
- An unknown golden-set `kind` is named as such instead of being reported as a row error.
- `POST /api/v1/runs` with `embedder: openrouter` and no key returned 500. It is a 503 with
  the reason.
- **Independent review, eight defects reproduced and fixed** (each has a regression test):
  an invariant field missing from every output scored flip 0.0 and passed (FAIL-0016). Jaccard
  thresholds were keyed by field, so a second invariant on the same field overwrote the first.
  One miss after a perfect judge baseline quarantined the judge for drift. A tie between two
  reference sets resolved differently per process. The invariant matrix did not mark a cell
  the second-mode gate had blocked. The mode chart dropped modes older than the pooled
  window. The reliability diagram drew empty bins at zero. A reordering probe whose sentences
  all read the same crashed mid-run instead of being refused at registration.
- `Dockerfile.test` had not built since the `seismograph` shim package was added, so
  `make check` failed at build. Fixed. Lint and the full suite pass in the Linux image on
  Python 3.12.
- The dashboard scrolled sideways at phone width.
- **Pre-push audit findings.** A non-editable install shipped `app/` without `app/engine`,
  so `seismo` crashed on import outside a checkout, the published Action failed for every
  other repository, and the "gate blocks a planted defect" job went green on that crash.
  Packages are now found, not listed, and the job runs the installed program from outside
  the checkout and requires a BLOCK verdict. Action inputs pass through the environment.
  A caller's system loads from the working directory without shadowing `app`. The ephemeris
  kernel fetch in CI is an explicit cached step. mypy reports the same on Linux and Windows.
  `.dockerignore` excludes local gitignored state.

### Added

Note: entries below that name `scripts/gates.py`, `scripts/gate.sh` or `scripts/g4_baseline.py`
describe operator tooling that is kept out of this repository, as are the private golden sets.

- `seismo run --suite kalika --profile daily --fail-on drift` — the deploy-pipeline
  command (`[project.scripts]`, `app/cli.py`). It calls a real target, runs every
  layer the suite declares, compares the verdicts against the committed baseline,
  and exits non-zero on any failed check, drift, or incomplete layer. A run that
  could not execute a declared layer is reported INCOMPLETE and fails — it never
  reads as a pass over fewer checks than the suite asked for.
- `app/suite.py`: suite definitions. `suites/<name>/` holds `suite.yaml` (target,
  layers, profiles), `cases/*.json` (golden records) and `policy/*.json` (the
  `assert` policy per layer). Loading is strict: a missing policy file or an empty
  case directory raises rather than running a smaller suite than the author wrote.
- `app/runner.py`: runs a suite and keeps the three failure kinds apart — failed
  checks, drift against the baseline, and incomplete layers. A baseline carries the
  report header (suite version, suite digest, target, judge model, rubric version)
  and a run under a different header is refused loudly, so a judge swap can never
  be read as a drifting system.
- `app/alerts.py`: one Resend alert on a failing run, to `nuwan@aigniteconsulting.ai`
  and nowhere else — the recipient is a constant, not an env var, so a misconfigured
  environment cannot redirect eval mail. A send Resend does not accept raises.
- `suites/kalika` v1: four synthetic golden cases (both hemispheres, a near-midnight
  birth, a sign-boundary lagna, a nakshatra-boundary moon — never customer data) and
  the two layers that decide without a model: `engine` (chart facts vs the reference)
  and `policy` (gemstone, ritual, medical and death-prediction prohibitions as
  deterministic assertions). Profiles: `daily` rotates three cases, `full` runs all
  three times so determinism is measured rather than assumed.
- `docker-compose.test.yml` plus `tests/fixtures/kalika_stub.py`: two fixture targets,
  one clean and one carrying the two defects g4 names (wrong lagna, gemstone
  prescription). Test-only — no deploy path or production env references them.
- `scripts/gates.py g4_cli_gate_and_alert`: brings the fixtures up, runs the CLI
  against both, and asserts the tampered run failed FOR THE PLANTED DEFECTS rather
  than merely exiting non-zero. Green 3/3, with a real Resend message id recorded in
  `reports/g4-alert-message-id.txt`.
- `scripts/g4_baseline.py`: re-records the fixture baseline after a suite change.
- `app/targets.py`: the two target adapters Seismograph uses to call the systems it
  evaluates. `McpTarget` is a streamable-HTTP MCP client — token in the query string,
  `tools/list` read at run time, arguments validated against the SERVED schema, both
  JSON and SSE response framings handled. `HttpTarget` takes method, URL and headers
  from env, sends a JSON body and extracts a dotted JSON path. Neither defaults a
  missing setting: absent configuration raises `TargetConfigError` (Standard 3).
- `target_calls` table (migration `0003_target_calls`): target id, adapter, route,
  arguments hash, raw response, latency, timestamp, error. Failed calls are stored
  as rows with `error` set, so a failed call reads as a failed run. `EXPECTED_TABLE_COUNT`
  9 → 10, asserted against a real Postgres (Standard 4).
- `scripts/target_integration.py`: drives both adapters against real endpoints and
  stores what came back; `scripts/gates.py g1_adapters_real` reads its summary.
- `app/checks.py`: the three check types. `assert` is deterministic code (JSON Schema,
  required and forbidden patterns, numeric tolerance, field equality) with no model in
  the loop. `grounded` has the judge extract chart facts into a fixed schema and lets
  plain code decide against the reference. `rubric` has the judge score a written rubric
  and quote the span it scored on; the code rejects a span that is not verbatim in the
  output, because a judge that cannot point at its evidence has not produced any.
- `data/checks/`: four versioned, content-hashed labelled sets — 44 samples per check
  type (22 clean, 22 planted across blatant/moderate/subtle tiers) over eleven synthetic
  charts, plus a 20-item judge-agreement set held disjoint from all three so model
  selection cannot inflate sensitivity. `scripts/build_check_sets.py` is their source.
- `scripts/judge_select.py`: reads the live OpenRouter model list at run time, filters to
  pinned, paid, structured-output text models, ranks cheapest-first and takes the first
  to clear a 0.85 agreement floor. Preflights the key so a dead credential is reported as
  such instead of as eight failing models. Writes `SEISMO_JUDGE_MODEL` to `.env`.
- `scripts/check_measure.py`: measures every type, reporting sensitivity and false-alarm
  rate with 95% Wilson intervals overall and per subtlety tier, into `check_report.md`
  and `check_report.json`. Thresholds are parsed from EVAL.md, never restated in code.
- `jsonschema` dependency, for the `assert` type's schema rule.

### Changed
- `scripts/gates.py`: `g1_adapters_real` implemented against docs/gates-spec.md.
  c1/c2 require a stored, non-empty result per adapter; c3 checks structurally by AST
  that no shipped module imports a mocking library and that exactly two adapters exist.
- `scripts/gates.py`: `g2_checks_catch_planted_defects` implemented in five criteria —
  labelled sets present, versioned, >=40 and evenly split; judge chosen live and recorded;
  all three types measured with Wilson intervals over non-zero samples; every EVAL.md
  threshold met; EVAL.md carrying the thresholds the run actually used plus one limits
  sentence per type. Judge calls are charged to LOOP_STATE.json in the step that spends them.
- EVAL.md: check-type section with the three thresholds (assert 0.95/0.05, grounded
  0.80/0.10, rubric 0.70/0.15), a limits sentence per type, and the judge-selection rule.

## [0.3.1] - 2026-07-27

### Added
- `GET /` serves a self-contained static HTML page: the app thesis, what it measures in plain
  language, the EVAL.md limits sentence verbatim, the endpoint list, and a build stamp
  (version, commit, build time) injected from Docker build args. No framework, no CDN, no
  JavaScript. Public by design; every API endpoint behind it still requires a bearer token.
- `scripts/gate.py` asserts the root route returns 200 `text/html` carrying the app name and
  the EVAL.md limits sentence verbatim, and fails on placeholder text. The estate gate sends a
  browser-shaped request to every hostname it reads out of `API_CONTRACT.md`.

### Fixed
- Every published hostname 404ed at `/` because no gate asserted what a browser receives
  (FAILURES FAIL-0011).


## [0.3.0] - 2026-07-27

> **BREAKING.** Business read endpoints now require the same bearer token as writes.
> **Migration:** send `Authorization: Bearer $SMOKE_TEST_TOKEN` on GET requests too.
> Unauthenticated reads previously returned data and now return 401. Development is
> unaffected while the token is empty.

### Eval (operating curve, 30 runs per cell, 95% Wilson intervals)
- Detects an abrupt mean shift of **1 sigma or larger** within a median of 5 monitored points
  at a false alarm rate of **0.0167/point**. Documented misses below that: 0.50 at 0.5 sigma,
  0.43 at 0.25 sigma; 0.87 at 1% format flake. Detection floor: 1 sigma.
- Acceptance bounds all PASS: sensitivity 1.00 at 3 sigma, 1.00 at 20% flake, false alarm
  rate 0.0167 <= 0.03, sensitivity monotone in magnitude, 18,000 monitored points with no
  vacuous cell. Report and SVG curve byte-reproducible.
- Key-gated back-check: 53/54 paraphrase variants accepted, 0.98 (95% CI 0.90-1.00) across
  nine statement types, all planted negative controls rejected.

### Changed
- The golden-defect suite was replaced by a swept operating curve. The previous suite's
  perfect scorecard reflected defect size, not detector sensitivity (FAILURES FAIL-0009).
- Metamorphic back-check rejects `numeric_drift`: cosine similarity accepted "120 days" as a
  paraphrase of "12 days" at 0.956 (FAILURES FAIL-0010).
- Embedder identity recorded in every report and checked against `eval_baseline.json`.
- Unused `sentence-transformers` (CUDA torch) dropped; image 5.6 GB -> 601 MB.
- `scripts/gate.py` enumerates routes and fails on any unguarded non-public route.

### Removed
- Unused `sentence-transformers` dependency (and the CUDA torch stack it pulled). No Phase 1
  code imports it; production images drop from ~5.7 GB toward the ~0.5 GB baseline
  (FAILURES FAIL-0008).

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
