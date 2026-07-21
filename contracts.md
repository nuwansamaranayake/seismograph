# API Contracts — Seismograph

Per Standard 6, every frontend call (Phase 2, Next.js) maps to exactly one backend endpoint, and CI
diffs this file against the live OpenAPI spec at `/openapi.json` (FastAPI also serves Swagger UI at
`/docs`). Endpoints marked *planned* are not implemented yet; only `/health` and `/api/v1/demo` exist
today.

| Frontend call (Phase 2) | Method | Path | Status | Notes |
|---|---|---|---|---|
| — (ops / liveness) | GET | `/health` | implemented | Returns `{status, env}`. No auth. |
| Demo dataset viewer | GET | `/api/v1/demo` | implemented | Returns `{items:[...]}` from `data/synthetic/`. Development-only; 503 outside development (Standard 3). |
| Compile a contract | POST | `/api/v1/contracts/compile` | planned — Phase 1 | Behavioral-contract YAML → deterministic experiment plan. |
| Launch a probe run | POST | `/api/v1/runs` | planned — Phase 1 | Sampler executes N runs × M configs against the system-under-test adapter. |
| Read consistency metrics | GET | `/api/v1/contracts/{id}/metrics` | planned — Phase 1 | Control-chart points, mode entropy, and ACI for a contract. |
| Read the release gate | GET | `/api/v1/contracts/{id}/gate` | planned — Phase 1 | Deterministic gate decision (block / pass) with the evidence attached. |
| Generate probe variants | POST | `/api/v1/probes/variants` | planned — Phase 2 | LLM proposes metamorphic variants; deterministic back-check disposes. |
| Judge calibration status | GET | `/api/v1/judges/calibration` | planned — Phase 2 | Judge-vs-anchor agreement and quarantine flags. |
| Fault attribution | POST | `/api/v1/attribution` | planned — Phase 3 | Controlled-intervention effect sizes per component. |
