# LOOP_STATE — Seismograph Phase 1

Branch: `phase-1`. Goal shape: PORTFOLIO_LEDGER first non-done cell = Seismograph Phase 1.
Phase 1 (ROADMAP + BLUEPRINT L336-341): contract YAML, sampler, canonicalizer, control charts,
paraphrase invariant, CLI report, golden-defect suite. Exit additionally requires: real eval
harness meeting EVAL.md thresholds, smoke hits a real business endpoint with real processing,
alembic migrations for the real schema with table count updated, CI eval job flips to required.

## Milestones (commit each; gate.py after each)

- [x] M1  EVAL.md numeric thresholds written first; LOOP_STATE; branch
- [x] M2  engine/contracts: YAML DSL -> validated Contract -> deterministic ExperimentPlan (+tests)
- [x] M3  engine/suts (synthetic programmable-defect SUTs) + engine/sampler + engine/canonicalize
         with pluggable Embedder (HashingEmbedder deterministic / OpenRouterEmbedder real) (+tests)
- [x] M4  engine/charts: individuals chart + p-chart, 3-sigma limits from baseline window,
         Western Electric rule 1 + run-of-8 drift rule; signals (+tests)
- [x] M5  scripts/eval.py: real golden-defect harness (drift@K, format flake p, clean windows);
         meets EVAL.md thresholds; deterministic seeds
- [x] M6  Postgres schema + alembic migration (contracts, probes, probe_variants, experiment_plans,
         runs, consistency_metrics, control_chart_points, gate_decisions); EXPECTED_TABLE_COUNT=9
- [x] M7  API: POST /api/v1/contracts, POST /api/v1/runs, GET /api/v1/reports/{contract};
         bearer token when SMOKE_TEST_TOKEN set; smoke_test.py extended to the real loop;
         CLI `python -m app.cli run --contract ... --sut demo --report out.md`
- [x] M8  engine/metamorphic: paraphrase variants via gateway (extraction model, JSON schema)
         + deterministic embedding-similarity back-check; one REAL gateway call observed in dev;
         unit tests use an injected stub gateway (explicit, typed — not a silent mock)
- [x] M9  CI: eval job -> required (drop continue-on-error, rename); README "What exists today",
         contracts.md, CHANGELOG updated for what actually landed; full gate + compose smoke

## DECISION log
- Phase 1 back-check = embedding cosine similarity only; NLI joins in Phase 2 with the full
  invariant set (NLIGate stays loud-raising until then). Grounds: MVP path L338 scopes Phase 1
  to the paraphrase invariant; blueprint back-check spec (emb+NLI) is fully met in Phase 2.
- Embedder is an explicit typed choice (config/CLI), never a fallback: OpenRouterEmbedder (real)
  for live use, HashingEmbedder (deterministic) for tests/golden-defect eval so `make eval` and
  the required CI job run keyless and reproducibly. Standard 3 intact: absence of a key can never
  silently swap the embedder; selection is declared by the caller.
- Mode-clustering eval (planted second mode) lands Phase 2 with clustering; attribution eval
  Phase 3. EVAL.md thresholds are structured per phase.
- Machine-local: Norton AV MITMs TLS; venvs need truststore sitecustomize (see portfolio memory).

## BLOCKED
(none)

## Next task
Phase 1 gates: containerized-stack smoke (last DONE-WHEN item), then report GATES_PASSED and stop (release only on explicit go).
