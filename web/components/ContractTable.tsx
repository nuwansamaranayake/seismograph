import { pct } from "@/lib/format";
import type { ContractSummary } from "@/lib/types";
import { GateBadge, SimulatorTag, Sparkline } from "./Bits";

export function ContractTable({ contracts }: { contracts: ContractSummary[] }) {
  return (
    <div className="table-wrap">
      <table className="data">
        <thead>
          <tr>
            <th>Contract</th>
            <th>Gate</th>
            <th>Worst flip rate, recent runs</th>
            <th className="num">Latest</th>
            <th className="num">Tolerance</th>
            <th className="num">Chart signals</th>
            <th className="num">Runs</th>
            <th>Last system</th>
          </tr>
        </thead>
        <tbody>
          {contracts.map((c) => (
            <tr key={c.name}>
              <td>
                <a href={`/contract/?name=${encodeURIComponent(c.name)}`}>{c.name}</a>
                <div className="dim small">{c.subject}</div>
              </td>
              <td>
                <GateBadge decision={c.latest?.decision ?? null} />
              </td>
              <td>
                <Sparkline series={c.trend} blocked={c.latest?.decision === "block"} />
              </td>
              <td className="num">{c.latest ? pct(c.latest.worst_flip_rate) : "—"}</td>
              <td className="num">{c.latest ? pct(c.latest.threshold) : "—"}</td>
              <td className="num">{c.chart_warm ? c.alarms : <span className="dim">warming</span>}</td>
              <td className="num">{c.runs}</td>
              <td>
                {c.latest ? (
                  <>
                    <code>{c.latest.sut}</code> <SimulatorTag />
                  </>
                ) : (
                  <span className="dim">never run</span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
