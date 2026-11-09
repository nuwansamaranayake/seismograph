# Seismograph Phase 2 and Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reach the ROADMAP Phase 2 exit: a team sees consistency trends and mode topology in a browser, and the gate runs as a GitHub check, with a measured quality score above 96.

**Architecture:** The deterministic engine gains four perturbation generators, outcome-mode clustering, and judge calibration statistics. FastAPI gains a read API over the existing tables plus two new ones. A Next.js static export in `web/` is served by FastAPI from `WEB_DIR`, the pattern CareerCompiler ships. No LLM issues any decision.

**Tech Stack:** Python 3.12+, FastAPI, SQLAlchemy Core, Alembic, pytest + pytest-cov, ruff, mypy. Next.js 15 static export, React 19, TypeScript, vitest + Testing Library, ESLint. Charts are hand-built SVG.

**Spec:** `docs/agent-legibility/2026-11-09-dashboard-truth-layer.md`, `ROADMAP.md` Phase 2, `PRD.md`.

## Global Constraints

- Every number on screen comes from the API or a committed report file. No literals in components.
- No mock fallback. A failed API call renders the error.
- Simulators are labelled "simulator" wherever they appear.
- A chart draws no limits before 8 baseline runs.
- Every non-public route takes an `authorization` header (`scripts/gate.py route_auth`).
- Schema change = new Alembic revision with frozen DDL + `EXPECTED_TABLE_COUNT` 10 -> 12 in `.env.example`, `Dockerfile`, tests.
- `contracts.md` and `CHANGELOG.md` updated in the commit that adds an endpoint.
- Copy rules: no em dashes, no semicolons, no "AI-powered", "intelligent", "smart".
- Quality gate: `python scripts/quality.py` exits 0 only when every component is at or above 96.
- No push, no deploy. Deploy command goes to BLOCKED.md (Tier 2: shared box, migration).

## Review Focus

- A contract that declares `reordering` on a one-sentence probe: registration is a 422 naming the probe, not a silent skip.
- A run where every sample is malformed: mode report shows one `malformed` mode, gate blocks, no division by zero.
- Dashboard opened with no token against an auth-on API: shows the connect prompt, never an empty "all green" board.
- Report requested for a contract with 1 to 8 runs: chart says warming with the count still needed.
- Judge calibration round with ids not in the anchor set: 422 listing the unknown ids, nothing stored.

---

### Task 1: Perturbation generators and the full invariant set

**Files:** Create `app/engine/perturb.py`. Modify `app/engine/contracts.py`, `app/engine/sampler.py`, `app/engine/suts.py`. Test `tests/test_perturb.py`, `tests/test_invariants.py`.

**Interfaces (produces):**
- `Perturbation.format`, `Perturbation.monotonic`. `Relation.monotonic`. `Invariant.order: list[str] | None`. `ProbeSeed.ladder: list[str] | None`.
- `perturb.variants_for(perturbation: Perturbation, seed_input: str, k: int) -> list[str]` for `irrelevant_context`, `reordering`, `format`. Deterministic. `reordering` raises `ValueError` under two sentences.
- `sampler.collect(...)` generates variants itself for the three deterministic perturbations.
- `sampler.collect_ladder(entry: PlanEntry, ladder: list[str], sut: SUT, t: int, seed: int) -> list[list[Sample]]`.
- `canonicalize.monotonic_violation_rate(rungs: list[list[Sample]], field: str, order: list[str]) -> float`: share of adjacent rungs whose modal value moves down the declared order.
- Simulators in `DEMO_SUTS`: `stable`, `noisy`, `jump`, `drift`, `flaky`, `bimodal`, `distractible`, `order-sensitive`, `format-sensitive`, `non-monotonic`, `policy`. `SUT_CATALOG: dict[str, dict]` with `summary` and `planted_defect`.

- [ ] Tests: each generator is deterministic and never returns the seed. Each planted simulator trips exactly its own invariant and `stable` trips none. A monotonic invariant without `order`, or with no laddered probe, fails validation.
- [ ] Implement. Run `pytest tests/test_perturb.py tests/test_invariants.py`. Commit.

### Task 2: Outcome-mode clustering

**Files:** Create `app/engine/modes.py`. Test `tests/test_modes.py`.

**Interfaces (produces):**
- `Mode(key: str, count: int, share: float, signature: dict, representative: str)`.
- `ModeReport(n: int, modes: list[Mode], second_mode_share: float, second_mode_low: float, second_mode_detected: bool)`.
- `cluster_modes(samples: list[Sample], fields: list[str]) -> ModeReport`. Signature = the invariant fields, lists as sorted sets. Malformed samples form the `malformed` mode. Modes sort by count then key.
- `pool(reports: list[ModeReport]) -> ModeReport` for a window of runs.
- `MODE_NOISE_FLOOR = 0.02`: detected when the Wilson 95% lower bound of the second mode share exceeds it.

- [ ] Tests: `bimodal` at share 0.10 passes the flip gate yet is detected over a pooled window. `stable` yields one mode. All malformed yields one mode.
- [ ] Implement. Commit.

### Task 3: Judge panel

**Files:** Create `app/engine/judges.py`. Test `tests/test_judges.py`.

**Interfaces (produces):**
- `agreement(verdicts: dict[str, str], anchors: dict[str, str]) -> Agreement(n, agree, rate, low, high, kappa)`. Unknown ids raise `ValueError` listing them.
- `quarantine(history: list[float], n: int, floor: float = 0.8) -> tuple[bool, str | None]`: `below_floor`, or `drift` when 8+ rounds exist and the latest rate is under the p-chart lower limit.
- `panel_verdict(votes: dict[str, str], quarantined: set[str], quorum: int = 2) -> PanelVerdict(label: str | None, counted: list[str], excluded: list[str], reason: str)`. Tie or under quorum gives `label=None`.

- [ ] Tests for each rule, including the tie and the all-quarantined panel. Implement. Commit.

### Task 4: Persistence and API

**Files:** Create `alembic/versions/0004_modes_and_judges.py`, `app/service.py`, `app/read_api.py`. Modify `app/db.py`, `app/routes.py`, `app/main.py`, `.env.example`, `Dockerfile`, `contracts.md`. Test `tests/test_read_api.py`, extend `tests/test_api.py`.

**Interfaces (produces):** tables `outcome_modes(run_id, probe_key, perturbation, n, modes, second_mode_share, second_mode_detected)` and `judge_calibrations(judge, round, n, agree, rate, kappa, quarantined, reason, created_at)`.

| Method | Path | Returns |
|---|---|---|
| GET | `/api/v1/overview` | counts, latest gate per contract, open alarms |
| GET | `/api/v1/contracts` | list with run count and latest gate |
| GET | `/api/v1/contracts/{name}` | yaml, invariants, probes, plan entries |
| GET | `/api/v1/reports/{name}` | existing fields + `charts.flip`, `charts.malformed`, `modes`, `matrix` |
| GET | `/api/v1/runs/{id}` | metrics, modes, gate evidence |
| GET | `/api/v1/suts` | simulator catalog |
| POST | `/api/v1/probes/variants` | accepted and rejected paraphrases. 503 without a configured model |
| GET, POST | `/api/v1/judges/calibration` | judge history and quarantine state |
| POST | `/api/v1/judges/panel` | panel verdict |
| GET | `/api/v1/golden` , `/api/v1/golden/{contract}` | committed golden-set reports under `reports/` |
| GET | `/api/v1/instrument` | published limits sentence and operating curve |

- [ ] Tests first for each route (auth on and off, 404, 422, empty states). Implement. Migration check on a throwaway Postgres asserts 12 tables. Commit.

### Task 5: CI release gate

**Files:** Create `action.yml`, `.github/workflows/gate.yml`. Modify `app/cli.py` (`seismo gate`), `README.md`. Test `tests/test_cli_gate.py`.

- [ ] `seismo gate --contract PATH --sut NAME --points N [--summary FILE]` exits 0 on pass, 1 on block, 2 on configuration error, and writes a markdown summary (defaults to `$GITHUB_STEP_SUMMARY`). Tests cover the three exit codes. Commit.

### Task 6: Dashboard

**Files:** Create `web/` (Next.js). Modify `Dockerfile`, `app/main.py` (serve `WEB_DIR`), `app/frontpage.py` kept as the no-web fallback.

Pages: `/` overview, `/contracts/`, `/contract/?name=`, `/run/?id=`, `/modes/?name=`, `/judges/`, `/golden/`, `/guide/`. Shared: `lib/api.ts` (typed fetch, token from sessionStorage, typed errors), `lib/scale.ts` (pure chart math), `components/` (ControlChart, ModeRiver, InvariantMatrix, GateBadge, ConnectPanel, states).

- [ ] vitest for `lib/` and every component and page state (loading, empty, warming, error, unauthorized). `npm run lint`, `npm run typecheck`, `npm test`, `npm run build` all exit 0. Commit.

### Task 7: Quality gate

**Files:** Create `scripts/quality.py`. Modify `pyproject.toml`, `Makefile`, `.github/workflows/ci.yml`.

- [ ] Components: backend coverage (line + branch), frontend coverage (min of the four v8 numbers), lint (ruff + eslint), types (mypy + tsc), test pass rate, complexity (share of functions at cyclomatic 10 or under). Writes `quality_report.json` and `quality_report.md`. Exit 0 only when every component is at or above 96. Iterate until green. Commit.

### Task 8: Verification, guide, docs

- [ ] Run the stack locally (Postgres + API + built web). Drive it in the browser. Capture screenshots into `docs/guide/img/`.
- [ ] Visual guide: `/guide/` in the app, plus a standalone `docs/guide/index.html`.
- [ ] README, CHANGELOG, ROADMAP, `contracts.md`, `/llms.txt`, BLOCKED.md deploy entry. Final gate run. Commit.
