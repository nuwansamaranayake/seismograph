"use client";
import { useState } from "react";
import { Sparkline } from "@/components/Bits";
import { Shell } from "@/components/Shell";
import { Data, Empty } from "@/components/States";
import { getJudges, panelVerdict, recordCalibration } from "@/lib/api";
import { parseMap, pct, quarantineText } from "@/lib/format";
import type { CalibrationResult, Judges, PanelResult } from "@/lib/types";
import { toApiError, useApi } from "@/lib/useApi";

function CalibrationForm({ judges, onRecorded }: { judges: Judges; onRecorded: () => void }) {
  const [judge, setJudge] = useState("");
  const [text, setText] = useState("");
  const [result, setResult] = useState<CalibrationResult | null>(null);
  const [error, setError] = useState("");
  const [first, second] = judges.anchors.ids;
  const example = `{"${first}": "${judges.anchors.labels[0]}", "${second}": "${judges.anchors.labels[1] ?? judges.anchors.labels[0]}"}`;

  async function submit() {
    setError("");
    setResult(null);
    const verdicts = parseMap(text);
    if (typeof verdicts === "string") return setError(verdicts);
    try {
      setResult(await recordCalibration(judge.trim(), verdicts));
      onRecorded();
    } catch (cause) {
      setError(toApiError(cause).message);
    }
  }

  return (
    <div className="card">
      <span className="label">Record a calibration round</span>
      <p className="dim">
        Give the judge the {judges.anchors.count} anchor items, collect its labels, and paste them here as JSON. The
        score is arithmetic against the anchor labels. The judge is never asked how good it is.
      </p>
      <label className="field">
        <span className="label">Judge name</span>
        <input type="text" value={judge} onChange={(e) => setJudge(e.target.value)} aria-label="Judge name" />
      </label>
      <label className="field" style={{ marginTop: "0.7rem" }}>
        <span className="label">Verdicts · anchor id to label</span>
        <textarea value={text} onChange={(e) => setText(e.target.value)} placeholder={example} aria-label="Verdicts JSON" />
      </label>
      <button type="button" onClick={submit} disabled={!judge.trim() || !text.trim()} style={{ marginTop: "0.7rem" }}>
        Score against anchors
      </button>
      {error ? (
        <p className="msg err" role="alert">
          {error}
        </p>
      ) : null}
      {result ? (
        <p className={`msg ${result.quarantined ? "err" : "ok"}`}>
          Round {result.round}: agreed on {result.agree} of {result.n} ({pct(result.rate)}, 95% interval {pct(result.low)}{" "}
          to {pct(result.high)}), kappa {result.kappa.toFixed(2)}.{" "}
          {result.quarantined
            ? `Quarantined: ${quarantineText(result.reason)}.`
            : "In good standing."}
        </p>
      ) : null}
    </div>
  );
}

function PanelForm() {
  const [text, setText] = useState("");
  const [result, setResult] = useState<PanelResult | null>(null);
  const [error, setError] = useState("");

  async function submit() {
    setError("");
    setResult(null);
    const votes = parseMap(text);
    if (typeof votes === "string") return setError(votes);
    try {
      setResult(await panelVerdict(votes));
    } catch (cause) {
      setError(toApiError(cause).message);
    }
  }

  return (
    <div className="card">
      <span className="label">Take a panel verdict</span>
      <p className="dim">
        Paste one vote per judge. Only calibrated judges in good standing are counted. A tie, or fewer than two counted
        judges, returns no verdict: an unjudged item is reported as unjudged.
      </p>
      <textarea
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder={'{"judge-a": "clean", "judge-b": "clean", "judge-c": "planted"}'}
        aria-label="Votes JSON"
      />
      <button type="button" onClick={submit} disabled={!text.trim()} style={{ marginTop: "0.7rem" }}>
        Decide
      </button>
      {error ? (
        <p className="msg err" role="alert">
          {error}
        </p>
      ) : null}
      {result ? (
        <div className="msg" data-testid="panel-result">
          <b>{result.label === null ? "No verdict" : `Verdict: ${result.label}`}</b> · {result.reason}
          {Object.entries(result.judges).map(([name, status]) => (
            <div key={name} className={status === "active" ? "dim" : "err"}>
              {name}: {status === "active" ? "counted" : `excluded, ${quarantineText(status)}`}
            </div>
          ))}
        </div>
      ) : null}
    </div>
  );
}

function Panel({ judges, onRecorded }: { judges: Judges; onRecorded: () => void }) {
  return (
    <div className="stack">
      <div className="card note">
        <span className="label">The standard</span>
        <p>
          {judges.anchors.count} labelled anchor items from <code>{judges.anchors.source}</code>, labels{" "}
          {judges.anchors.labels.map((l) => `"${l}"`).join(" and ")}. A judge is quarantined when it agrees with fewer
          than {pct(judges.floor, 0)} of them, or when its agreement falls under the lower control limit of its own last{" "}
          {judges.drift_baseline} rounds.
        </p>
      </div>
      {judges.judges.length ? (
        <div className="card">
          <span className="label">Judges</span>
          <div className="table-wrap">
            <table className="data">
              <thead>
                <tr>
                  <th>Judge</th>
                  <th>Standing</th>
                  <th>Agreement by round</th>
                  <th className="num">Latest</th>
                  <th className="num">Kappa</th>
                  <th className="num">Rounds</th>
                </tr>
              </thead>
              <tbody>
                {judges.judges.map((j) => (
                  <tr key={j.judge}>
                    <td>
                      <code>{j.judge}</code>
                    </td>
                    <td>
                      {j.quarantined ? (
                        <span className="badge block">quarantined · {quarantineText(j.reason)}</span>
                      ) : (
                        <span className="badge pass">active</span>
                      )}
                    </td>
                    <td>
                      <Sparkline series={j.rounds.map((r) => r.rate)} blocked={j.quarantined} />
                    </td>
                    <td className="num">{pct(j.latest_rate)}</td>
                    <td className="num">{j.latest_kappa.toFixed(2)}</td>
                    <td className="num">{j.rounds.length}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      ) : (
        <Empty title="No judge has been calibrated yet">Record a first round below.</Empty>
      )}
      <div className="grid two">
        <CalibrationForm judges={judges} onRecorded={onRecorded} />
        <PanelForm />
      </div>
    </div>
  );
}

export default function JudgesPage() {
  const { state, reload } = useApi(getJudges);
  return (
    <Shell active="judges">
      <span className="label">Judge panel</span>
      <h1>
        Who checks <em>the checker?</em>
      </h1>
      <p className="lede">
        A model that scores other models is a measuring instrument. It is trusted only while it agrees with a known
        standard. This page calibrates each judge against labelled anchors and quarantines the ones that stop agreeing.
      </p>
      <Data state={state} reload={reload} what="the judge panel">
        {(judges) => <Panel judges={judges} onRecorded={reload} />}
      </Data>
    </Shell>
  );
}
