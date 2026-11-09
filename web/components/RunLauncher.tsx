"use client";
import { useState } from "react";
import { launchRun, listSimulators } from "@/lib/api";
import { pct } from "@/lib/format";
import type { RunResult } from "@/lib/types";
import { toApiError, useApi } from "@/lib/useApi";
import { GateBadge, SimulatorTag } from "./Bits";
import { Data } from "./States";

/**
 * Launch runs of a contract against a built-in simulator. Each run is one point on the
 * chart, at time step t. The next t defaults to the number of runs already recorded, so
 * a time-based planted defect arrives on schedule.
 */
export function RunLauncher({
  contract,
  nextT,
  lastSut,
  onDone,
}: {
  contract: string;
  nextT: number;
  lastSut?: string;
  onDone: () => void;
}) {
  const { state, reload } = useApi(listSimulators);
  // One chart is one system. Default to the system this contract was last run against.
  const [sut, setSut] = useState(lastSut ?? "stable");
  const [count, setCount] = useState(1);
  const [seed, setSeed] = useState(7);
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState("");
  const [last, setLast] = useState<RunResult | null>(null);
  const [error, setError] = useState("");

  async function run() {
    setBusy(true);
    setError("");
    try {
      let result: RunResult | null = null;
      for (let i = 0; i < count; i++) {
        setProgress(`run ${i + 1} of ${count}`);
        result = await launchRun(contract, sut, nextT + i, seed);
      }
      setLast(result);
    } catch (cause) {
      setError(toApiError(cause).message);
    } finally {
      setBusy(false);
      setProgress("");
      onDone();
    }
  }

  return (
    <div className="card">
      <span className="label">Launch a run</span>
      <Data state={state} reload={reload} what="the simulator catalog">
        {(simulators) => {
          const chosen = simulators.find((s) => s.name === sut);
          return (
            <>
              <div className="form-row">
                <label className="field">
                  <span className="label">System under test</span>
                  <select value={sut} onChange={(e) => setSut(e.target.value)} aria-label="System under test">
                    {simulators.map((s) => (
                      <option key={s.name} value={s.name}>
                        {s.name}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="field">
                  <span className="label">Runs</span>
                  <select value={count} onChange={(e) => setCount(Number(e.target.value))} aria-label="Runs">
                    {[1, 4, 9, 12].map((n) => (
                      <option key={n} value={n}>
                        {n}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="field">
                  <span className="label">Seed</span>
                  <input type="number" value={seed} onChange={(e) => setSeed(Number(e.target.value))} aria-label="Seed" />
                </label>
                <button type="button" onClick={run} disabled={busy}>
                  {busy ? progress : `Run from t = ${nextT}`}
                </button>
              </div>
              {chosen ? (
                <p className="msg dim">
                  <SimulatorTag /> {chosen.summary}{" "}
                  {chosen.planted_defect ? `Planted defect: ${chosen.planted_defect}.` : "No planted defect."}
                </p>
              ) : null}
            </>
          );
        }}
      </Data>
      {error ? (
        <p className="msg err" role="alert">
          {error}
        </p>
      ) : null}
      {last ? (
        <div className="msg" data-testid="last-run">
          <GateBadge decision={last.gate} /> run {last.run_id}: {last.cells} cells, worst flip rate{" "}
          <span className="num">{pct(last.worst_flip_rate)}</span> against a tolerance of{" "}
          <span className="num">{pct(last.threshold)}</span>.
          {last.worst_cell ? ` Worst cell: ${last.worst_cell.probe} under ${last.worst_cell.perturbation}.` : ""}
          {last.reasons.map((reason) => (
            <div key={reason} className="err">
              {reason}
            </div>
          ))}
          {last.skipped.length ? (
            <div className="dim">
              {last.skipped.length} cell{last.skipped.length === 1 ? "" : "s"} not measured: {last.skipped[0]?.reason}.
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
