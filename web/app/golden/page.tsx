"use client";
import { useState } from "react";
import { Stat } from "@/components/Bits";
import { ControlChart } from "@/components/ControlChart";
import { Reliability } from "@/components/Reliability";
import { Shell } from "@/components/Shell";
import { Data, Empty } from "@/components/States";
import { getGolden, listGolden } from "@/lib/api";
import { metricText, pct, when } from "@/lib/format";
import type { GoldenDetail, GoldenSummary } from "@/lib/types";
import { useApi } from "@/lib/useApi";

function Report({ detail }: { detail: GoldenDetail }) {
  const { run, calibration, drift } = detail;
  const chart = drift?.control_chart;
  return (
    <div className="stack">
      <div className="grid stats">
        <Stat label="Gate" value={run.passed ? "pass" : "block"} tone={run.passed ? "good" : "bad"} />
        <Stat label="Golden items" value={run.probes} note={`${run.samples} runs each`} />
        <Stat label="Calls recorded" value={run.records} />
        <Stat label="Latency p50 / p95" value={`${Math.round(run.latency_ms.p50)} / ${Math.round(run.latency_ms.p95)}`} note="milliseconds" />
        <Stat label="Cost of the run" value={`$${run.usage.cost_usd.toFixed(4)}`} note={`${run.usage.input_tokens} input tokens`} />
      </div>
      <div className="card note">
        <span className="label">Scope of these numbers</span>
        <p>
          One model build (<code>{run.model}</code>), one golden set of {run.probes} items, run on {when(run.run_at)}.
          They describe that build on that set. They are not a general accuracy claim.
        </p>
      </div>
      <div className="grid two">
        <div className="card">
          <span className="label">Measured</span>
          <table className="data kv">
            <tbody>
              {Object.entries(run.metrics).map(([key, value]) => (
                <tr key={key}>
                  <td className="dim">{key.replaceAll("_", " ")}</td>
                  <td className="num">{metricText(key, value)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <span className="label" style={{ display: "block", marginTop: "0.9rem" }}>
            Declared gate
          </span>
          <table className="data kv">
            <tbody>
              {Object.entries(run.gate).map(([key, value]) => (
                <tr key={key}>
                  <td className="dim">{key.replaceAll("_", " ")}</td>
                  <td className="num">{pct(value)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {calibration ? (
          <Reliability bins={calibration.bins} ece={calibration.expected_calibration_error} />
        ) : (
          <Empty title="No calibration report">
            Run <code>seismo calibrate --contract {detail.contract}</code> to write one.
          </Empty>
        )}
      </div>
      {drift && chart ? (
        <>
          <div className="card">
            <span className="label">
              Drift · {drift.model_a} against {drift.model_b}
            </span>
            <p>
              Overall agreement <span className="num">{pct(drift.overall_agreement, 2)}</span>.{" "}
              {drift.model_a_served === drift.model_b_served
                ? `Both names resolved to the same served build (${drift.model_a_served}), so this measures run to run stability, not a version change.`
                : `Served builds: ${drift.model_a_served} and ${drift.model_b_served}.`}
            </p>
            <table className="data">
              <thead>
                <tr>
                  <th>Question</th>
                  <th className="num">Agreement</th>
                  <th className="num">Pairs</th>
                  <th className="num">Mean total variation</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(drift.per_question).map(([question, q]) => (
                  <tr key={question}>
                    <td>{question.replaceAll("_", " ")}</td>
                    <td className="num">{pct(q.agreement_rate, 2)}</td>
                    <td className="num">{q.n_pairs}</td>
                    <td className="num">{q.mean_total_variation.toFixed(4)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <ControlChart
            title={`Disagreement per batch of ${chart.batch_size} items`}
            values={chart.series}
            chart={{
              warm: chart.points.length > 0,
              baseline_needed: chart.baseline_points,
              runs_until_warm: 0,
              points: chart.points,
            }}
          />
        </>
      ) : null}
    </div>
  );
}

function Browser({ reports }: { reports: GoldenSummary[] }) {
  const [chosen, setChosen] = useState(reports[0]?.contract ?? "");
  const { state, reload } = useApi(chosen ? () => getGolden(chosen) : null, chosen);
  if (!reports.length) {
    return (
      <Empty title="No golden-set reports on this instance">
        A report appears here after <code>seismo run --contract &lt;name&gt;</code> writes one under{" "}
        <code>reports/</code>.
      </Empty>
    );
  }
  return (
    <div className="stack">
      <label className="field" style={{ maxWidth: "26rem" }}>
        <span className="label">Golden-set contract</span>
        <select value={chosen} onChange={(e) => setChosen(e.target.value)} aria-label="Golden-set contract">
          {reports.map((r) => (
            <option key={r.contract} value={r.contract}>
              {r.contract} · {r.model}
            </option>
          ))}
        </select>
      </label>
      <Data key={chosen} state={state} reload={reload} what="the report">
        {(detail) => <Report detail={detail} />}
      </Data>
    </div>
  );
}

export default function GoldenPage() {
  const { state, reload } = useApi(listGolden);
  return (
    <Shell active="golden">
      <span className="label">Golden sets</span>
      <h1>
        Typed judgments, <em>scored against labels</em>
      </h1>
      <p className="lede">
        Where ground truth exists, a contract can carry a labelled golden set. These are the committed reports of real
        runs against a live model: recall, false positives, calibration, and agreement between two model versions.
      </p>
      <Data state={state} reload={reload} what="the golden-set reports">
        {(reports) => <Browser reports={reports} />}
      </Data>
    </Shell>
  );
}
