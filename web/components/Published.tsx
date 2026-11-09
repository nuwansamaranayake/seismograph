import published from "@/lib/published.generated.json";

type Row = Record<string, string>;

function CurveTable({ caption, first, rows }: { caption: string; first: string; rows: Row[] }) {
  return (
    <div className="table-wrap">
      <table className="data">
        <caption className="label" style={{ textAlign: "left", paddingBottom: "0.4rem" }}>
          {caption}
        </caption>
        <thead>
          <tr>
            <th>{first}</th>
            <th className="num">Detected</th>
            <th className="num">Sensitivity</th>
            <th className="num">95% CI</th>
            <th className="num">Median latency</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row[first]}>
              <td className="num">{row[first]}</td>
              <td className="num">{row.detected}</td>
              <td className="num">{row.sensitivity}</td>
              <td className="num">{row["95% CI"]}</td>
              <td className="num">{row["median latency"]} points</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** The limits sentence, verbatim from EVAL.md. Read at build time, never typed here. */
export function Limits() {
  return (
    <div className="card note">
      <span className="label">Published limits · verbatim from EVAL.md · measured on synthetic systems</span>
      <p data-testid="limits">{published.limits}</p>
    </div>
  );
}

/** What the instrument catches and what it misses, from eval_report.md. Misses included. */
export function OperatingCurve() {
  return (
    <div className="stack">
      <CurveTable caption="Abrupt shift in the flip rate" first="shift" rows={published.shift} />
      <CurveTable caption="Gradual drift" first="ramp to" rows={published.drift} />
      <CurveTable caption="Malformed output (p-chart)" first="flake rate" rows={published.flake} />
      <p className="dim small">
        False alarm rate {published.falseAlarm.rate} per monitored point (95% CI {published.falseAlarm.low} to{" "}
        {published.falseAlarm.high}). Design: {published.design}. Embedder: <code>{published.embedder}</code>. Reproduce
        with <code>python scripts/eval.py</code>.
      </p>
    </div>
  );
}
