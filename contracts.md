# API Contracts — Seismograph

Per Standard 6, every frontend call maps to exactly one backend endpoint. The dashboard's calls
live in `web/lib/api.ts`, one function per row below, and `tests/test_contracts_doc.py` diffs this
table against the live OpenAPI spec at `/openapi.json` (FastAPI also serves Swagger UI at `/docs`).
Rows marked *planned* are not implemented.

Every `/api/v1` route except `/api/v1/demo` requires `Authorization: Bearer <SMOKE_TEST_TOKEN>`
when the token is set. An empty token turns auth off and is allowed in development only.

| Frontend call | Method | Path | Status | Notes |
|---|---|---|---|---|
| Dashboard and guide (browser) | GET | `/` | implemented | The Next.js static export when `WEB_DIR` holds a build. Otherwise the self-contained fallback page. Public by design. Carries the EVAL.md limits sentence verbatim. |
| — (ops / liveness) | GET | `/health` | implemented | Returns `{status, env}`. No auth. |
| — (agents) | GET | `/llms.txt` | implemented | Plain text: what it is, what it measures, the limits sentence, endpoints. No auth. |
| Demo dataset viewer | GET | `/api/v1/demo` | implemented | Returns `{items:[...]}` from `data/synthetic/`. Development-only; 503 outside development (Standard 3). |
| `getOverview` | GET | `/api/v1/overview` | implemented | Counts, latest gate per contract, chart alarms, cells with a detected second mode, judge quarantine count. An empty instance returns zeros. |
| `listContracts` | GET | `/api/v1/contracts` | implemented | Every contract with run count, latest gate, alarm state and a 24 run trend. |
| `registerContract` | POST | `/api/v1/contracts` | implemented | Behavioral-contract YAML validated and compiled to a content-hashed experiment plan; persisted. 409 on duplicate names. 422 names the probe when a declared perturbation cannot run on it. |
| `getContract` | GET | `/api/v1/contracts/{name}` | implemented | YAML, invariants, gate policy, probes, plan entries, generated variants. |
| `launchRun` | POST | `/api/v1/runs` | implemented | Executes every executable plan cell against a named simulator: repeat run, irrelevance, order, format, monotonicity, and paraphrase when accepted variants exist. Stores metrics, outcome modes and the gate decision with its reasons. A run with zero executable cells is a 422, never a recorded pass. |
| `getRun` | GET | `/api/v1/runs/{id}` | implemented | Gate evidence, invariant matrix and outcome modes of one run. |
| `getReport` | GET | `/api/v1/reports/{contract}` | implemented | Run series, X-chart (flip rate) and p-chart (malformed rate) once 9 runs exist, mode topology pooled over the last 12 runs, invariant matrix of the latest run. |
| `listSimulators` | GET | `/api/v1/suts` | implemented | The in-process simulators and the defect planted in each. Labelled `kind: simulator`. |
| `generateVariants` | POST | `/api/v1/probes/variants` | implemented | A model proposes paraphrases; the deterministic back-check accepts or rejects each. 503 when no model is configured. |
| `getJudges` | GET | `/api/v1/judges/calibration` | implemented | Anchor set description, each judge's calibration rounds and quarantine state. |
| `recordCalibration` | POST | `/api/v1/judges/calibration` | implemented | Scores a judge's verdicts against the anchors: rate, Wilson interval, kappa, quarantine decision. 422 on ids outside the anchor set. |
| `panelVerdict` | POST | `/api/v1/judges/panel` | implemented | Majority among calibrated, non-quarantined judges. No quorum or a tie returns `label: null`. |
| `listGolden` | GET | `/api/v1/golden` | implemented | Committed golden-set reports under `reports/`. |
| `getGolden` | GET | `/api/v1/golden/{contract}` | implemented | The `run`, `calibration` and `drift` reports of one golden-set contract. Missing ones are `null`. |
| Fault attribution | POST | `/api/v1/attribution` | planned — Phase 3 | Controlled-intervention effect sizes per component. |
