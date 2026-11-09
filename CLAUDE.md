# Seismograph

An AI eval system for measuring LLM performance consistency (statistical process control).

Part of the AiGNITE portfolio. This project inherits the AiGNITE engineering standards below.

## Thesis
The LLM senses. Deterministic code decides. Humans approve action. Every claim carries provenance.

## Engineering standards (AiGNITE law)
1. Fix root causes, never symptoms. Curl the endpoint, query the DB, read the logs, then fix the source.
2. Every deploy runs a smoke test against real business endpoints with a real token, asserting non-empty schema-valid data.
3. No silent mock or fallback data outside development. Fail loud with a typed error.
4. After every migration, assert the expected table count.
5. Before any fix, document what is actually broken versus reported. No frontend patches over a broken backend.
6. Keep contracts.md current: every frontend call mapped to its backend endpoint.
7. Remember GoviHub: silent table failures plus mock fallback cost five days. Instrument against it.

## Definition of done for any change
- Types pass, lint passes, tests pass.
- make smoke passes against a real running instance.
- make eval passes its acceptance thresholds (see EVAL.md).
- contracts.md and CHANGELOG.md updated. Conventional Commit message.

## Stack
Python 3.12, FastAPI, Pydantic v2, Postgres 16 (pgvector, JSONB), Redis, OpenRouter via the
groundwork gateway, Docker Compose. Frontend: Next.js 15 static export in `web/`, served by
FastAPI from `WEB_DIR` (no node in production).

## Commands
- `python scripts/quality.py` the measured quality gate. Nine components, each >= 96.
- `cd web && npm run lint && npm run typecheck && npm test && npm run build`
- `python scripts/dev_serve.py` then `python scripts/seed_demo.py` for a local walkthrough.
- `python scripts/build_guide.py` after EVAL.md, eval_report.md or the guide screenshots change.
- Tests run with `WEB_DIR` unset, so the app under test serves the single-file fallback page.

## LLM access
Never call a provider SDK directly. Use groundwork.gateway.LLMGateway. It reads OPENROUTER_API_KEY,
pins model IDs from env, forces JSON-schema structured output, and traces every call.
