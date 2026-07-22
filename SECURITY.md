# Security — Seismograph

Baseline: the **OWASP Top 10 for LLM Applications (2025)** and the **NIST AI Risk Management
Framework — Generative AI Profile (NIST-AI-600-1)**. Seismograph runs untrusted systems under test
and lets an LLM propose test inputs, so its trust boundaries are stated plainly: the LLM is a sensor
(it proposes variants and drafts narration), deterministic code computes every metric and decision,
and the system under test is treated as untrusted output — never as an instruction source.

## OWASP LLM mapping

| ID | Risk | Seismograph control |
|---|---|---|
| LLM01 | Prompt injection | System-under-test outputs and retrieved documents are data, never instructions. Metamorphic variant text and SUT responses travel in a separate channel from system prompts; red-team injection cases ship in the eval suite. |
| LLM02 | Sensitive information disclosure | Traces store prompt hashes and typed claim objects, not raw payloads by default; a local-model mode exists for private stages so production data need not leave the boundary. |
| LLM04 | Data and model poisoning | Metamorphic variants are quarantined until back-checked; rejected variants are logged, not silently used, so a poisoned probe cannot enter the bank. |
| LLM05 | Improper output handling | Every LLM output — variants, judge verdicts, narration — passes a deterministic gate before use: embedding+NLI back-check for variants, anchor calibration for judges, verified-stats-only for narration. Nothing generated is trusted unchecked. |
| LLM06 | Excessive agency | The LLM decides nothing consequential. Contract compilation, control limits, gate decisions, and the cost ledger are deterministic. Gates block builds; humans approve anything that acts. |
| LLM09 | Misinformation | The narrator emits incident reports grounded in verified statistics only; a judge whose anchor agreement decays is quarantined and flagged rather than trusted. |
| LLM10 | Unbounded consumption | Distribution testing multiplies token spend by N. Hard budgets cap tokens and run counts; the planner computes the minimum N per probe within a declared budget. |

## NIST AI RMF (GenAI Profile)

Seismograph maps to the Profile's functions: **Measure** (its entire purpose — quantifying
consistency, drift, and capability), **Manage** (release gates and re-baselining discipline),
**Map** (behavioral contracts make intended behavior explicit and versioned), and **Govern**
(immutable traces and auditable ADRs). Measuring a self-calibrating judge speaks directly to the
Profile's concern with the reliability of evaluation instruments themselves.

## Secrets

No secret is committed. The OpenRouter key and all model IDs come from `.env` / the environment via
the groundwork gateway (see `.env.example`, values blank by default). The demo runs on synthetic
data with no key. Provider SDKs are never called directly — the gateway pins model versions, forces
JSON-schema structured output, and traces every call.

## Reporting a vulnerability

Report suspected vulnerabilities privately to **nuwans@hotmail.com**. Do not open a public issue.
You will receive an acknowledgment within 72 hours. Please allow time to investigate and ship a fix
before any public disclosure; a coordinated disclosure timeline will be agreed with you.
