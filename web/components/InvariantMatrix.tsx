import { pct, perturbationLabel } from "@/lib/format";
import type { MatrixRow } from "@/lib/types";

const ORDER = ["repeat_run", "paraphrase", "irrelevant_context", "reordering", "format", "monotonic"];

/**
 * Probes down, perturbations across. A cell is the flip rate of that probe under that
 * change to its input: 0% means the answer held. A dashed cell was not measured in this
 * run, which is not the same as holding.
 */
export function InvariantMatrix({ rows }: { rows: MatrixRow[] }) {
  if (rows.length === 0) return <p className="dim">No cells measured yet.</p>;
  const probes = [...new Set(rows.map((r) => r.probe))];
  const columns = ORDER.filter((p) => rows.some((r) => r.perturbation === p));
  const cell = (probe: string, perturbation: string) =>
    rows.find((r) => r.probe === probe && r.perturbation === perturbation);
  return (
    <div className="table-wrap">
      <table className="matrix">
        <thead>
          <tr>
            <th scope="col">Probe</th>
            {columns.map((p) => (
              <th scope="col" key={p}>
                {perturbationLabel(p)}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {probes.map((probe) => (
            <tr key={probe}>
              <th scope="row">{probe}</th>
              {columns.map((p) => {
                const found = cell(probe, p);
                if (!found) {
                  return (
                    <td key={p} className="absent" title="not measured in this run">
                      not run
                    </td>
                  );
                }
                const detail =
                  `${found.n} samples · flip ${pct(found.flip_rate)} · malformed ${pct(found.malformed_rate)}` +
                  Object.entries(found.jaccard_mean)
                    .map(([field, value]) => ` · jaccard ${field} ${value.toFixed(3)}`)
                    .join("") +
                  (found.second_mode_share > 0 ? ` · second mode ${pct(found.second_mode_share)}` : "");
                return (
                  <td key={p} className={found.violated ? "violated" : "held"} title={detail}>
                    {pct(found.flip_rate)}
                    {found.malformed_rate > 0 ? <span className="small"> · {pct(found.malformed_rate)} malformed</span> : null}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
