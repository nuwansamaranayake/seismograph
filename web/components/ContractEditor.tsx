"use client";
import { useState } from "react";
import { registerContract } from "@/lib/api";
import type { RegisterResult } from "@/lib/types";
import { toApiError } from "@/lib/useApi";

// A starting point for the editor, not data: the same contract the repository ships at
// contracts/refund-full-invariants.yaml, with a name the user is expected to change.
export const TEMPLATE = `contract: my-refund-contract
subject: support-agent
invariants:
  # The decision must be the same answer every time, with an unrelated sentence
  # added, with the sentences reordered, and with the formatting changed.
  - field: eligibility_decision
    under: [repeat_run, irrelevant_context, reordering, format]
    relation: equal
  # The cited policies must overlap by at least 85% between repeated runs.
  - field: cited_policy_ids
    under: [repeat_run]
    relation: jaccard_at_least
    threshold: 0.85
allowed_variation:
  - field: response_wording
    rule: semantically_equivalent
run_policy: {samples: 20, configs: 1, confidence: 0.95}
gate: {max_decision_flip_rate: 0.10, max_malformed_rate: 0.05}
probes:
  - id: refund-basic
    input: "Customer bought a blender 12 days ago, unopened. Are they refund eligible?"
`;

export function ContractEditor({ onRegistered }: { onRegistered: () => void }) {
  const [yaml, setYaml] = useState(TEMPLATE);
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState<RegisterResult | null>(null);
  const [error, setError] = useState("");

  async function submit() {
    setBusy(true);
    setError("");
    setDone(null);
    try {
      setDone(await registerContract(yaml));
      onRegistered();
    } catch (cause) {
      setError(toApiError(cause).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="card">
      <span className="label">Register a contract</span>
      <p className="dim">
        A contract says which fields of the answer must not change, under which changes to the input, and how much
        variation the gate tolerates. It compiles to an experiment plan with a content hash.
      </p>
      <textarea value={yaml} onChange={(e) => setYaml(e.target.value)} rows={18} spellCheck={false} aria-label="Contract YAML" />
      <div className="row" style={{ marginTop: "0.7rem" }}>
        <button type="button" onClick={submit} disabled={busy || !yaml.trim()}>
          {busy ? "compiling" : "Register and compile"}
        </button>
        {done ? (
          <span className="msg ok">
            Registered <a href={`/contract/?name=${encodeURIComponent(done.contract)}`}>{done.contract}</a>: plan{" "}
            <code>{done.plan_id}</code>, {done.entries} cells.
          </span>
        ) : null}
      </div>
      {error ? (
        <p className="msg err" role="alert">
          {error}
        </p>
      ) : null}
    </div>
  );
}
