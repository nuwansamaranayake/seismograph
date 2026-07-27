# Failure Gallery — Seismograph

An honest record of things that broke, why, and what changed. A curated gallery beats a buried
changelog: it is where the doctrine earns its keep. Every entry names the *reported* symptom and
the *diagnosed* root cause separately (Standard 5).

> The entry below is a seeded template. Replace it with the first real failure you diagnose.

## FAIL-0001 (template) — Demo showed no data

- **Date**: 2026-07-21
- **Surface**: `GET /api/v1/demo`
- **Reported symptom**: The demo view rendered "no data".
- **Diagnosed cause**: `data/synthetic/demo.json` existed but was an empty array. The endpoint
  correctly raised HTTP 500 (`"synthetic fixture is empty"`) instead of silently returning `[]`.
- **Root cause**: Fixture authored empty during scaffold.
- **Fix**: Populated the fixture with a non-empty synthetic dataset. The smoke test asserts
  `items` is non-empty, so this cannot regress silently.
- **Doctrine link**: Standard 3 (no silent mock/fallback) and Standard 2 (smoke asserts non-empty).

## FAIL-0002 — `make migrate` failed on a clean machine (check_migrations driver)

- **Date**: 2026-07-21
- **Surface**: `scripts/check_migrations.py` (`make migrate`)
- **Reported symptom**: The migration-count check errored immediately after a successful
  `alembic upgrade`.
- **Diagnosed cause**: The script did `DATABASE_URL.replace("+psycopg", "")`, turning
  `postgresql+psycopg://...` into a bare `postgresql://...`. SQLAlchemy routes the bare URL to the
  **psycopg2** driver, which is not a declared dependency (the apps pin `psycopg` v3). `alembic`
  itself succeeded because it kept the `+psycopg` URL, so the failure surfaced only at the check step.
- **Root cause**: Driver mismatch between the migration step (psycopg v3) and the check step (psycopg2).
- **Fix**: Use `DATABASE_URL` unmodified so the check reuses the declared psycopg v3 driver. Proven
  against a real Postgres: `MIGRATION OK: 1 tables` at `EXPECTED_TABLE_COUNT=1`, and
  `MIGRATION CHECK FAILED: expected 2 tables, found 1` (rc=1) at `EXPECTED_TABLE_COUNT=2`.
- **Doctrine link**: Standard 4 (assert the table count) and Standard 1 (fix the root cause — the
  driver — not the symptom).

## FAIL-0003 — First public CI run: smoke job died before the stack started

- **Date**: 2026-07-23
- **Surface**: GitHub Actions `smoke` job (`docker compose up -d --build`)
- **Reported symptom**: CI run red on the first push; compose exited immediately.
- **Diagnosed cause (from the run log)**: `env file ... .env not found`. `docker-compose.yml`
  declares `env_file: .env`, and `.env` is gitignored by design, so it does not exist in a CI
  checkout. A second, deterministic failure sat behind it: the Dockerfile's `pip install .` now
  resolves `aignite-groundwork` from a `git+https` URL, and `python:3.12-slim` ships no git.
- **Root cause**: The CI environment was never given the dev-shaped inputs the compose file
  assumes (env file present, git available in the build image).
- **Fix**: CI smoke job copies the committed `.env.example` to `.env` before compose (the same
  step the README gives a stranger); Dockerfile installs git before `pip install`.
- **Doctrine link**: Standard 1 (root cause from the real log, not a retry) and Standard 2 (the
  smoke gate exists to catch exactly this before anyone calls the estate "green").

## FAIL-0004 — API tests died on SQLite thread affinity

- **Date**: 2026-07-23
- **Surface**: `tests/test_api.py` (pytest gate)
- **Reported symptom**: 4 API tests failed with `SQLite objects created in a thread can only
  be used in that same thread`.
- **Diagnosed cause**: FastAPI's TestClient serves requests on a worker thread while the test
  fixture opened the in-memory SQLite connection on the main thread; sqlite3 connections are
  thread-bound by default.
- **Fix**: `connect_args={"check_same_thread": False}` with `StaticPool` on the test engine —
  the standard arrangement for sharing one in-memory database with a threaded test server.
- **Doctrine link**: the gate caught it before commit (tests are part of `scripts/gate.py`);
  the failing trace, not a guess, named the root cause (Standard 1/5).

## FAIL-0005 — Release CI red: token mismatch, unmigrated CI database, ruff default-select skew

- **Date**: 2026-07-23
- **Surface**: GitHub Actions release run 30049712444 (lint job, smoke job)
- **Reported symptom**: lint failed with 18 errors that pass locally; smoke failed with
  `contract register: 401 missing or invalid bearer token`.
- **Diagnosed causes (from the run logs)**: (1) CI's smoke client sent `ci-token` while the
  container's env (copied from `.env.example`) sets `dev-smoke-token` — the newly enforced
  bearer auth correctly rejected the mismatch; (2) behind it, the CI compose database never
  receives migrations (locally alembic was run from the host); (3) CI installs unpinned
  latest ruff, whose broadened default ruleset (e.g. TRY004) redefined "lint passes".
- **Fixes**: CI smoke uses the token from `.env.example`; the container now runs
  `alembic upgrade head` + the table-count check before serving (Standard 4 at startup);
  `[tool.ruff.lint] select` pins the ruleset so lint semantics stop depending on ruff's
  release cadence.
- **Doctrine link**: Standard 1 (root causes from the logs, three distinct ones — not one
  retry); Standard 4 (a container serving over an unmigrated schema is the GoviHub failure).
  The 401 is the auth gate working as designed; the gallery records it because the estate,
  not the app, was misconfigured.

## FAIL-0006 — Adversarial review wave: 12 confirmed findings before release

- **Date**: 2026-07-27
- **Surface**: run gate (`app/routes.py`, `app/cli.py`), golden-defect eval
  (`app/engine/golden.py`), auth (`app/main.py`), migrations, CI, docs.
- **Reported symptom**: none — every finding was surfaced by an adversarial code review and
  independently reproduced against this code before any user hit it.
- **Diagnosed causes (the worst four)**: (1) CRITICAL — a paraphrase-only contract compiled
  to zero executable cells and `POST /runs` persisted a `pass` gate decision with evidence
  `{"cells": 0}`: a recorded pass over zero measurements, directly contradicting "a plan
  cell is never silently skipped". (2) MAJOR — 100% malformed output passed the run gate as
  healthy: unparsed samples vanish from the flip rate, and nothing gated the malformed rate.
  (3) MAJOR — an empty `SMOKE_TEST_TOKEN` (the shipped default) silently disabled bearer
  auth with no environment guard, so a production deploy without a dotenv served mutating
  endpoints unauthenticated. (4) MAJOR — the golden-defect eval ran its healthy baseline
  with zero noise, so chart sigma floored at 1e-6, planted defects measured ~10^5 sigma, and
  false alarms were structurally impossible: the CI-required eval passed by construction.
  Plus eight more (dead jaccard thresholds, silent CI install fallbacks, a skippable
  table-count check, an unfrozen migration, a string-equality hole in the trivial-copy
  back-check, a 500 on registration races, a gate/server token mismatch, and a quickstart
  that could not print SMOKE OK as documented).
- **Fixes**: zero-cell runs are a typed 422/exit-2; `max_malformed_rate` and declared
  jaccard thresholds gate decisions; production startup refuses an empty token; the eval
  baseline carries real noise with defects sized in sigma (false-alarm bound honestly
  revised 0.01 -> 0.03, documented in EVAL.md); migration 0002 frozen as explicit DDL;
  check_migrations fails loud when unconfigured; CI fallbacks deleted; near-copies rejected
  on similarity alone; races return 409; the gate injects its token into the spawned server.
- **Doctrine link**: Standards 2/3/4 throughout. The review found what the green gate could
  not: several of these defects were invisible precisely because the checks that should have
  caught them were the broken part.

## FAIL-0007 — Production business data was world-readable: read endpoints skipped bearer auth

- **Date**: 2026-07-27
- **Surface**: `GET /api/v1/reports/{contract}`
- **Reported symptom**: none. Every gate was green, CI was green, and the estate smoke
  passed: the smoke client always sent a token, so it never asked what happens without one.
- **Diagnosed cause**: mutating endpoints called `_auth(authorization)`; these read
  endpoints never took an `authorization` header at all. Verified against live production
  from an unauthenticated client on the public internet, which returned HTTP 200 and
  contract reports with gate decisions and metrics.
- **Root cause**: the adversarial review found this class and fixed the two instances it
  happened to surface (CareerCompiler `get_fit`, Mycelium `get_answer`); the class was
  never swept estate-wide, so four apps shipped with open reads.
- **Fix**: every business read now calls the same `_auth` as the writes. Development
  semantics are unchanged (an empty `SMOKE_TEST_TOKEN` leaves auth off, and production
  startup already refuses an empty token). Regression test added:
  `test_business_reads_require_bearer_when_token_set` asserts 401 without a bearer.
- **Doctrine link**: Standard 6 — this is exactly why the estate needed `API_CONTRACT.md`
  with an auth column: an endpoint nobody wrote down is an endpoint nobody audited. The
  production business-loop audit (curl with and WITHOUT a token) caught what six green
  CI runs could not.

## FAIL-0008 — Undeclared-but-installed CUDA torch: a 5 GB dependency nothing imports

- **Date**: 2026-07-27
- **Surface**: `pyproject.toml` dependency list; production image build on beacon-gom
- **Reported symptom**: image builds took many minutes and pip installed the full
  nvidia-cu13 / triton / torch stack on a CPU-only VPS.
- **Diagnosed cause**: `sentence-transformers` was declared from the original scaffold, but
  no Phase 1 code imports it (verified by grep across `app/` and `scripts/`): embeddings go
  through `app/engine/embedding.py`, which is a deterministic hashing embedder plus an
  HTTP OpenRouter embedder. The declaration alone pulled CUDA torch into every image.
- **Measured impact**: images carrying it were 5.6-5.8 GB; the two apps without it were
  496-773 MB. Roughly 5 GB of unused, CVE-bearing surface per image.
- **Fix**: dependency removed, with a comment recording why and when to re-add it (the
  phase that actually imports a local cross-encoder). Tests unchanged and still green.
- **Doctrine link**: a dependency you do not import is a claim you cannot back. It also
  slowed every deploy, which is how it was noticed while shipping a security fix.
