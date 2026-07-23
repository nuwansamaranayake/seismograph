# API Contracts — Seismograph

Per Standard 6, every frontend call (Phase 2, Next.js) maps to exactly one backend endpoint, and CI
diffs this file against the live OpenAPI spec at `/openapi.json` (FastAPI also serves Swagger UI at
`/docs`). Endpoints marked *planned* are not implemented yet; only `/health` and `/api/v1/demo` exist
today.

| Frontend call (Phase 2) | Method | Path | Status | Notes |
|---|---|---|---|---|
| — (ops / liveness) | GET | `/health` | implemented | Returns `{status, env}`. No auth. |
| Demo dataset viewer | GET | `/api/v1/demo` | implemented | Returns `{items:[...]}` from `data/synthetic/`. Development-only; 503 outside development (Standard 3). |
| Register a contract | POST | `/api/v1/contracts` | implemented | Behavioral-contract YAML validated and compiled to a content-hashed experiment plan; persisted. Bearer auth when `SMOKE_TEST_TOKEN` is set. 409 on duplicate names. |
| Launch a probe run | POST | `/api/v1/runs` | implemented | Executes the plan's repeat_run cells against a named in-process SUT, stores consistency metrics and a gate decision. Paraphrase cells execute once variants are generated. |
| Read the report | GET | `/api/v1/reports/{contract}` | implemented | Metrics history, gate decisions, and X-chart points once 8+ runs warm the baseline. |
| Generate probe variants | POST | `/api/v1/probes/variants` | planned — Phase 2 | LLM proposes metamorphic variants; deterministic back-check disposes. |
| Judge calibration status | GET | `/api/v1/judges/calibration` | planned — Phase 2 | Judge-vs-anchor agreement and quarantine flags. |
| Fault attribution | POST | `/api/v1/attribution` | planned — Phase 3 | Controlled-intervention effect sizes per component. |
