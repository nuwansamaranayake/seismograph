import { pct } from "@/lib/format";
import { type Box, linear, round } from "@/lib/scale";
import type { CalibrationBin } from "@/lib/types";

const BOX: Box = { width: 420, height: 320, left: 46, right: 14, top: 14, bottom: 34 };

/**
 * Reliability diagram: stated confidence across, measured accuracy up. A calibrated
 * system sits on the diagonal. A bar below it is overconfidence: the system said 90%
 * and was right less often than that.
 */
type FilledBin = CalibrationBin & { accuracy: number; mean_confidence: number };

export function Reliability({ bins: allBins, ece }: { bins: CalibrationBin[]; ece: number }) {
  const right = BOX.width - BOX.right;
  const bottom = BOX.height - BOX.bottom;
  // An empty bin has no accuracy and no confidence. Drawing it at zero would put a bar
  // that says "0% right" where nothing was measured.
  const bins = allBins.filter((b): b is FilledBin => b.count > 0 && b.accuracy !== null && b.mean_confidence !== null);
  const empty = allBins.length - bins.length;
  const lo = Math.min(0.5, ...bins.map((b) => b.mean_confidence));
  const x = linear(lo, 1, BOX.left, right);
  const y = linear(0, 1, bottom, BOX.top);
  const width = Math.max((right - BOX.left) / Math.max(bins.length, 1) - 8, 6);
  return (
    <div className="card">
      <div className="row spread">
        <span className="label">Calibration</span>
        <span className="badge">ECE {pct(ece)}</span>
      </div>
      <svg className="chart" viewBox={`0 0 ${BOX.width} ${BOX.height}`} role="img" aria-label="reliability diagram">
        {[0, 0.25, 0.5, 0.75, 1].map((tick) => (
          <g key={tick}>
            <line className="grid-line" x1={BOX.left} x2={right} y1={round(y(tick))} y2={round(y(tick))} />
            <text x={BOX.left - 6} y={round(y(tick)) + 3} textAnchor="end">
              {pct(tick, 0)}
            </text>
          </g>
        ))}
        <line className="limit" data-line="diagonal" x1={round(x(lo))} y1={round(y(lo))} x2={round(x(1))} y2={round(y(1))} />
        {bins.map((bin) => {
          const over = bin.accuracy < bin.mean_confidence;
          return (
            <g key={bin.bin}>
              <rect
                data-bin={bin.bin}
                x={round(x(bin.mean_confidence) - width / 2)}
                width={round(width)}
                y={round(y(bin.accuracy))}
                height={round(bottom - y(bin.accuracy))}
                fill={over ? "var(--gold)" : "var(--trace)"}
                opacity="0.75"
              >
                <title>
                  {bin.bin}: said {pct(bin.mean_confidence)}, right {pct(bin.accuracy)}, n={bin.count}
                </title>
              </rect>
              <text x={round(x(bin.mean_confidence))} y={BOX.height - 18} textAnchor="middle">
                {bin.bin}
              </text>
              <text x={round(x(bin.mean_confidence))} y={BOX.height - 6} textAnchor="middle">
                n={bin.count}
              </text>
            </g>
          );
        })}
      </svg>
      {empty ? (
        <p className="msg dim">
          {empty} confidence bin{empty === 1 ? "" : "s"} held no answers and {empty === 1 ? "is" : "are"} not drawn.
        </p>
      ) : null}
      <div className="legend">
        <span>
          <i className="gold" />
          perfect calibration
        </span>
        <span>
          <i className="swatch" style={{ background: "var(--gold)" }} />
          overconfident bin
        </span>
        <span>
          <i className="swatch" style={{ background: "var(--trace)" }} />
          at or above its stated confidence
        </span>
      </div>
    </div>
  );
}
