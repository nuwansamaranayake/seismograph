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
