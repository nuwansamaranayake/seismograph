# Seismograph dashboard: truth layer

Date: 2026-11-09. Subject: company product (open source eval instrument).
Surfaces covered: the web dashboard, the in-app guide, `contracts.md`, README, `/llms.txt`.
Evidence was read from the repo on this date. Nothing here is taken from memory.

## 1. Diagnosis

Clear and specific today:

- One sentence carries the product: Seismograph runs the same question at an AI system many
  times and charts how much the answers move.
- The published limits sentence is a real measurement with its misses included
  (`eval_report.md`, reproduced by `python scripts/eval.py`).
- The front page says "There is no web application here". That becomes false the moment the
  dashboard ships and must be replaced, not left beside the new UI.

Vague or at risk of being flattened by an agent:

- "Manufacturing-grade math" and "self-calibrating judge" are README phrases with no number
  attached. An agent will repeat them as capability claims.
- "Fault attribution" appears in the README bet but no attribution code exists.
- The Jev results (recall 1.000, top-1 0.9825) are strong and easy to over-read. They hold for
  one model build on one golden set.

## 2. Truth layer

Canonical facts a human or agent may repeat:

| Fact | Value | Source |
|---|---|---|
| What it is | Open source eval instrument that measures behavioural consistency of an LLM application as a distribution | README, PRD |
| Core method | N repeated runs per probe, canonicalized to flip rate, malformed rate, Jaccard mean, semantic variance, then an individuals control chart | `app/engine/` |
| Detection floor | Abrupt mean shift of 1 sigma or larger, median 5 monitored points, 40 samples per point | `eval_report.md` |
| False alarm rate | 0.0167 per monitored point (95% CI 0.0108 to 0.0256) | `eval_report.md` |
| Documented miss | 0.5 sigma shift caught 0.50 of the time. 0.25 sigma caught 0.43 | `eval_report.md` |
| Check types | assert, grounded, rubric. Sensitivity 100.0%, 95.5%, 72.7% on 22 planted defects each. Zero false alarms on 22 clean each | `check_report.md` |
| Gate | Deterministic. Blocks on flip rate, malformed rate, or a declared Jaccard threshold. Zero measured cells is a 422, never a pass | `app/routes.py` |
| Who decides | Code. No LLM issues a gate decision | DOCTRINE.md, `app/routes.py` |
| Licence | Apache 2.0 | LICENSE |
| Price | Free. Self hosted. No meter | README |

Audience: AI product engineers, open source maintainers, eng leads who own a ship decision,
on-call engineers triaging a behaviour change.

Not for:

- Teams that want tracing, a prompt playground, or dataset management.
- Single sample answer quality as the headline number.
- Causal claims from production data.

Constraints the dashboard must state on screen:

- A control chart needs 8 baseline runs before it draws limits. Before that it says "warming".
- Demo systems under test are in-process simulators with planted defects. They are labelled as
  simulators wherever they appear.
- Jev numbers apply to `typesafe/jev-1.13-20260917` on the named golden set only.

## 3. Claims and evidence map

| Claim | Proof on hand | Gap | Rewrite to ship |
|---|---|---|---|
| "Detects silent model drift" | Operating curve, 30 runs per cell | Synthetic process only. No field incident | "Detects a planted 1 sigma shift within a median of 5 points on synthetic systems. Smaller shifts are missed about half the time." |
| "Manufacturing-grade math" | Individuals chart, Western Electric rules, Wilson intervals in code | Phrase has no number | "Individuals control chart with limits derived from the baseline moving range." |
| "Self-calibrating judge" | Judge selection script and agreement set | No panel, no quarantine shipped before this change | State only what the judge panel page measures: agreement with the human anchor set, and the quarantine rule. |
| "Finds the hidden second mode" | Nothing before this change | New feature | Claim only after the planted second mode test passes. Quote the planted share it was tested at. |
| "Fault attribution" | None | Not built | Do not claim. Roadmap page only, marked planned. |
| "Recall 1.000 on the Kalika QA gate" | `reports/kalika-qa-gate/run.json`, 225 of 225 | One model build, 45 seeded excerpts, self-seeded defects | "225 of 225 seeded defects flagged on 130 excerpts. FPR 0.012. One model build." |
| "Works in CI" | `seismo run --fail-on drift`, exit codes tested | GitHub check not wired before this change | Claim after the workflow file runs green in this repo. |

## 4. AI-washing risk register

| Risk | Where | Severity | Control |
|---|---|---|---|
| Dashboard shows a green "pass" over zero measurements | Any empty state | High | Empty states say "no runs yet". The API already refuses a zero cell run. |
| Simulated data read as production data | Demo mode, guide screenshots | High | Persistent "simulator" badge on every demo SUT and a banner in demo mode. No mock fallback when the API fails. The UI shows the error. |
| A chart drawn before the baseline is warm | Control chart | Medium | No limits rendered until 8 runs. Counter shows runs still needed. |
| "AI-powered" language | Hero and guide copy | Medium | The words AI-powered, intelligent, smart do not appear. The product measures AI systems. It is statistics. |
| Jev calibration read as general accuracy | Calibration page | Medium | Model build id, golden set size, and ECE shown in the page header. |
| Planned features shown as present | Navigation | Medium | Planned items live on one roadmap panel. No dead nav entries. |
| Numbers typed into copy by hand | Any page | High | Every number on screen is fetched from the API or a committed report file. No literals in components. |

## 5. Human memory layer

- The seismograph metaphor: you do not judge one tremor, you watch the trace.
- "Accuracy 87% demos better than Cpk 1.1, right up until the first silent model update burns
  you." Keep it. It is an opinion, labelled as one.
- The published miss table. Showing what the instrument cannot see is the trust moment.
- The "silent earthquake" scenario: a policy assistant that passes a conventional eval while
  flipping refund decisions between identical runs. The guide walks this scenario with the
  drifting simulator.

## 6. Agent surface plan

| Surface | Change |
|---|---|
| `/` | Dashboard replaces the "This is an API" page. The limits sentence stays verbatim. |
| `/guide/` | Visual guide. Five steps: declare, run, read the chart, read the modes, gate the build. |
| `/llms.txt` | New. Plain text: what it is, what it measures, the limits sentence, the not-for list, endpoint list, licence. |
| `/openapi.json` | Stays public. Every dashboard call maps to one row in `contracts.md`. |
| `contracts.md` | Updated in the same commit as each new endpoint. Planned rows stay marked planned. |
| README | "What exists today" gains the dashboard and the invariant set only after their tests pass. |
| JSON-LD | `SoftwareApplication` with name, category, licence, price 0. No rating, no review fields. |

## 7. Technical deliverables backlog

| Rank | Deliverable | Impact | Effort |
|---|---|---|---|
| 1 | Read API for the dashboard (contracts, runs, chart, modes, suites, Jev reports) | High | Medium |
| 2 | Dashboard with honest empty, warming, and error states | High | High |
| 3 | Visual guide built from real screenshots of a real local run | High | Medium |
| 4 | `/llms.txt` and JSON-LD | Medium | Low |
| 5 | `contracts.md` and README truth pass | Medium | Low |
| 6 | Roadmap panel that separates shipped from planned | Medium | Low |
