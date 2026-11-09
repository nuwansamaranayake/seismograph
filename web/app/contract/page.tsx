"use client";
import { useState } from "react";
import { GateBadge, SimulatorTag } from "@/components/Bits";
import { ControlChart } from "@/components/ControlChart";
import { InvariantMatrix } from "@/components/InvariantMatrix";
import { ModeRiver } from "@/components/Modes";
import { RunLauncher } from "@/components/RunLauncher";
import { Shell } from "@/components/Shell";
import { Data, Empty, Loading } from "@/components/States";
import { generateVariants, getContract, getReport } from "@/lib/api";
import { pct, perturbationLabel } from "@/lib/format";
import type { ContractDetail, Report, VariantsResult } from "@/lib/types";
import { toApiError, useApi, useQueryParam } from "@/lib/useApi";

function Paraphrases({ detail, onChanged }: { detail: ContractDetail; onChanged: () => void }) {
  const [busy, setBusy] = useState("");
  const [result, setResult] = useState<VariantsResult | null>(null);
  const [error, setError] = useState("");
  const declared = detail.invariants.some((i) => i.under.includes("paraphrase"));
  if (!declared) return null;
  const accepted = detail.variants.filter((v) => v.accepted).length;

  async function generate(probe: string) {
    setBusy(probe);
    setError("");
    setResult(null);
    try {
      setResult(await generateVariants(detail.name, probe, 5));
      onChanged();
    } catch (cause) {
      setError(toApiError(cause).message);
    } finally {
      setBusy("");
    }
  }

  return (
    <div className="card">
      <span className="label">Paraphrase variants</span>
      <p className="dim">
        Paraphrase is the one change to the input a model has to propose. Each candidate is then checked by code:
        similar enough to mean the same thing, different enough to be a real variant, and carrying no new number.{" "}
        {accepted
          ? `${accepted} accepted variant${accepted === 1 ? "" : "s"} on record. Paraphrase cells run.`
          : "No accepted variants on record, so paraphrase cells are reported as not measured."}
      </p>
      <div className="row">
        {detail.probes.map((probe) => (
          <button key={probe.id} type="button" className="secondary" disabled={Boolean(busy)} onClick={() => generate(probe.id)}>
            {busy === probe.id ? "asking the model" : `Generate for ${probe.id}`}
          </button>
        ))}
      </div>
      {error ? (
        <p className="msg err" role="alert">
          {error}
        </p>
      ) : null}
      {result ? (
        <p className="msg ok">
          {result.accepted} accepted, {result.rejected} rejected by the back-check
          {result.variants.filter((v) => !v.accepted).length
            ? ` (${[...new Set(result.variants.filter((v) => !v.accepted).map((v) => v.reason))].join(", ")})`
            : ""}
          .
        </p>
      ) : null}
    </div>
  );
}

function Board({ report, onRan }: { report: Report; onRan: () => void }) {
  const flagged = report.modes.findIndex((cell) => cell.pooled.second_mode_detected);
  const [cellIndex, setCellIndex] = useState(-1);
  const shown = report.modes[cellIndex >= 0 ? cellIndex : Math.max(flagged, 0)];
  const flips = report.series.map((s) => s.worst_flip_rate);
  const malformed = report.series.map((s) => s.worst_malformed_rate);
  const gate = report.gate_policy;
  return (
    <div className="stack">
      <div className="row">
        <GateBadge decision={report.latest_gate?.decision ?? null} />
        <span className="badge">tolerance · flip {pct(gate.max_decision_flip_rate)}</span>
        <span className="badge">malformed {pct(gate.max_malformed_rate)}</span>
        <span className="badge">plan {report.plan_id}</span>
        <span className="badge">{report.runs} runs</span>
      </div>
      <RunLauncher
        contract={report.contract}
        nextT={report.runs}
        lastSut={report.series[report.series.length - 1]?.sut}
        onDone={onRan}
      />
      {report.runs === 0 ? (
        <Empty title="No runs recorded for this contract">
          Launch a run above. Nine runs warm the control chart: eight set the baseline and the ninth is the first point
          judged against it.
        </Empty>
      ) : (
        <>
          <div className="grid two">
            <ControlChart
              title="Worst flip rate per run (X chart)"
              values={flips}
              chart={report.charts.flip}
              tolerance={gate.max_decision_flip_rate}
              toleranceLabel="gate tolerance"
            />
            <ControlChart
              title="Malformed output per run (p chart)"
              values={malformed}
              chart={report.charts.malformed}
              tolerance={gate.max_malformed_rate}
              toleranceLabel="gate tolerance"
            />
          </div>
          <div className="card">
            <span className="label">Invariant matrix · latest run</span>
            <InvariantMatrix rows={report.matrix} />
            {report.notes.map((note) => (
              <p key={note} className="msg dim">
                Not measured: {note}
              </p>
            ))}
          </div>
          {shown ? (
            <>
              {report.modes.length > 1 ? (
                <label className="field" style={{ maxWidth: "26rem" }}>
                  <span className="label">Mode topology of cell</span>
                  <select
                    value={report.modes.indexOf(shown)}
                    onChange={(e) => setCellIndex(Number(e.target.value))}
                    aria-label="Mode topology of cell"
                  >
                    {report.modes.map((cell, i) => (
                      <option key={`${cell.probe}/${cell.perturbation}`} value={i}>
                        {cell.probe} · {perturbationLabel(cell.perturbation)}
                        {cell.pooled.second_mode_detected ? " · second mode" : ""}
                      </option>
                    ))}
                  </select>
                </label>
              ) : null}
              <ModeRiver cell={shown} noiseFloor={report.mode_noise_floor} />
            </>
          ) : null}
          <div className="card">
            <span className="label">Run history</span>
            <div className="table-wrap">
              <table className="data">
                <thead>
                  <tr>
                    <th className="num">t</th>
                    <th>Gate</th>
                    <th>System</th>
                    <th className="num">Worst flip</th>
                    <th className="num">Malformed</th>
                    <th>Why</th>
                  </tr>
                </thead>
                <tbody>
                  {[...report.series].reverse().map((run) => (
                    <tr key={run.run_id}>
                      <td className="num">
                        <a href={`/run/?id=${run.run_id}`}>{run.t}</a>
                      </td>
                      <td>
                        <GateBadge decision={run.decision} />
                      </td>
                      <td>
                        <code>{run.sut}</code> <SimulatorTag />
                      </td>
                      <td className="num">{pct(run.worst_flip_rate)}</td>
                      <td className="num">{pct(run.worst_malformed_rate)}</td>
                      <td className="dim small">{run.reasons.join(". ") || "every declared tolerance held"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </>
      )}
    </div>
  );
}

function Definition({ detail, onChanged }: { detail: ContractDetail; onChanged: () => void }) {
  return (
    <div className="stack">
      <Paraphrases detail={detail} onChanged={onChanged} />
      <div className="card">
        <span className="label">
          The contract · {detail.run_policy.samples} samples per cell · {detail.plan.length} cells
        </span>
        <pre>{detail.yaml}</pre>
      </div>
    </div>
  );
}

export default function ContractPage() {
  const name = useQueryParam("name");
  const report = useApi(name ? () => getReport(name) : null, name ?? "");
  const detail = useApi(name ? () => getContract(name) : null, name ?? "");
  const refresh = () => {
    report.reload();
    detail.reload();
  };
  return (
    <Shell active="contracts">
      <span className="label">Contract</span>
      <h1>{name || "Contract"}</h1>
      {name === undefined ? (
        <Loading what="the address" />
      ) : name === null || name === "" ? (
        <Empty title="No contract named in the address">
          Open a contract from the <a href="/contracts/">contracts list</a>.
        </Empty>
      ) : (
        <div className="stack">
          <Data state={report.state} reload={report.reload} what="the report">
            {(data) => <Board report={data} onRan={refresh} />}
          </Data>
          <Data state={detail.state} reload={detail.reload} what="the contract">
            {(data) => <Definition detail={data} onChanged={refresh} />}
          </Data>
        </div>
      )}
    </Shell>
  );
}
