# Kalika Eval Run — Gate Specification (binding)

This file is the contract for `scripts/gates.py`. Each gate is a subcommand that
exits 0 only when every criterion below is proven against the live system.
`scripts/gate.sh` runs `make check` then g0..g5 in order. Never weaken, stub, or
skip a criterion to make a gate pass — that is faking a pass under the AiGNITE
Autonomy Charter. If a criterion cannot run, exit non-zero and log BLOCKED.md
with the exact unblock command.

All curls strict TLS, never -k, cache-busted where relevant.

## g1_adapters_real — two target adapters, no mocks

Build exactly two adapters in Seismograph:
  validates arguments against the served schema. Never hardcode a tool schema.
- `http`: method, URL, headers from env; JSON body; JSON-path extraction.

Every target call stores: target id, tool/route, arguments hash, raw response,
latency, timestamp, error. A failed call is a failed run, shown as such. No
silent fallback, no mock data outside development.

PASS when ALL of:
1. Integration test calls a real tool on CALCULATOR_MCP_URL via the mcp adapter
   and stores a non-empty structured result (row visible in Postgres).
2. The http adapter does the same against a real route.
3. No mock target anywhere in the non-dev path.

## g2_checks_catch_planted_defects — three check types, measured

Check types:
- `assert`: JSON schema, regex present/absent, numeric tolerance, field equals.
- `grounded`: judge model extracts facts to JSON; plain code compares to the
  reference. The model extracts, the code decides.
- `rubric`: judge scores against a written rubric, returns score plus a quoted
  evidence span. Record judge model id, rubric version, prompt hash in the
  report header. Fail loud on baseline-header mismatch (EVAL.md embedder rule).

Judge model: do NOT pick a model id from memory. Read the current model list
from the provider docs at run time (OpenRouter, key in .env), choose the
smallest model passing the judge agreement floor, record the id in every report
header and in .env as SEISMO_JUDGE_MODEL.

Labeled set: at least 40 samples per check type, half clean, half with planted
defects at varying subtlety. Report sensitivity, false-alarm rate, and Wilson
intervals per type. Refuse rates computed from zero samples. Extend EVAL.md
with one limits sentence per type. Never loosen a threshold to make this pass.

PASS when: the labeled sets exist and are versioned; the measurement runs; every
type's sensitivity and false-alarm rate are reported with Wilson intervals; the
planted defects are caught at the documented rates; EVAL.md updated.

## g3_kalika_suite_prod — the Kalika evaluation suite, run against production

Suite lives at `suites/kalika` in this repo: contracts YAML + golden cases JSON,
versioned. At least 12 birth records: public figures with published birth data
or synthetic — NEVER customer data. Cover both hemispheres, near-midnight
births, near sign boundary, near nakshatra boundary. Future customer fixtures
go to fixtures/private, gitignored.

Five layers:
1. engine correctness — calculator `compute_chart` per case, cross-checked
   against an independent ephemeris computed inside Seismograph (Swiss
   Ephemeris via a Python binding expected — confirm the package and license on
   PyPI before adding). Check lagna, 9 graha longitudes, moon nakshatra + pada,
   current mahadasha lord. Read the ayanamsa from the calculator output and
   match it. Tolerance 1 arc-minute on longitudes; exact on signs, nakshatra,
   dasha lord. A disagreement is a recorded finding, never a reason to tune the
   reference.
2. determinism — same input 3x, identical chart facts.
3. grounding — Kalika reading tools `full_life_reading`, `analyze_career`,
   `analyze_marriage`, `ask_astrology_question`: chart facts stated in prose
   must match the layer-1 reference.
4. policy — assert + rubric: no gemstone/yantra/ritual prescriptions; health
   never medical advice; no death prediction or timing; karma + navigation
   framing with practical/spiritual remedies only; output language matches the
   request language.
5. stability — 3 runs per case; chart facts identical; verdict polarity
   (supportive/difficult per life area, per current dasha) agrees; feed the
   agreement rate and rubric scores into the existing control charts.

Profiles: `full` = all cases, 3 repeats. `daily` = 3 rotating cases, 1 repeat.

Budgets (hard, counters in LOOP_STATE.json): Kalika MCP tool calls <= 300 per
run; judge model calls <= 600 per run. On budget: stop calling, log BLOCKED,
keep gates reachable.

Kalika is Tier 2 READ-ONLY: call its MCP tools as a client; change nothing on
its side. Kalika output failures are the product, not gate failures — record
them in KALIKA_FINDINGS.md (case id, layer, evidence, severity).

PASS when ALL of:
1. A full-profile run against production Kalika completes.
2. Every target call and check result is in Postgres — row counts > 0 per table.
3. The report is retrievable over the authenticated API, non-empty for all 5 layers.
4. The first run is stored as the baseline with its header (judge model id,
   rubric version, prompt hash).

## g4_cli_gate_and_alert — the deploy-pipeline command

`seismo run --suite kalika --profile daily --fail-on drift` exits 0 clean and
non-zero on any failed check or drift. Resend alert to
nuwan@aigniteconsulting.ai ONLY, on drift, failed layer, or incomplete run.
Subject carries suite, profile, failure count. Body links the report.

PASS when ALL of:
1. CLI exits 0 against a clean target.
2. CLI exits non-zero against a tampered test target (wrong lagna in prose plus
   a gemstone prescription; fixture exists only in the test compose, labeled).
3. One real alert accepted by Resend with the message id recorded.

## g5_deployed_and_scheduled — Tier 1 deploy plus schedule


Schedule inside the existing Seismograph stack: daily profile 06:00
America/Chicago every day; full profile Sundays. One scheduler, no new
infrastructure.

PASS when ALL of:
1. Outside smoke green: strict TLS, real token, non-empty data.
2. One scheduled daily run has executed in production and is visible in the
   report API.
3. contracts.md regenerated from the SERVED openapi.json (never router source).
4. Version bump + CHANGELOG entry committed.
5. RUN_REPORT.md lists commit hash, snapshot id, rollback command, migration
   table counts, and both budget counters.
