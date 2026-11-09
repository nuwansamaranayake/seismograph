import { pct, perturbationLabel, signatureText } from "@/lib/format";
import { type Box, linear, round, stack } from "@/lib/scale";
import type { Mode, ModeCell } from "@/lib/types";

const BOX: Box = { width: 760, height: 190, left: 52, right: 16, top: 12, bottom: 26 };
const MALFORMED = "malformed";
const PALETTE = ["var(--trace)", "var(--gold)", "#6fa8ff", "#c586ff", "#ff9d5c", "#7fe3c8"];

/** Colour by rank in the pooled report, so the usual answer is always the trace colour. */
export function modeColor(key: string, order: string[]): string {
  if (key === MALFORMED) return "var(--red)";
  return PALETTE[order.indexOf(key) % PALETTE.length] ?? "var(--text-dim)";
}

export function ModeList({ modes, order }: { modes: Mode[]; order: string[] }) {
  return (
    <div>
      {modes.map((mode, i) => (
        <div className="mode" key={mode.key}>
          <span className="chipcolor" style={{ background: modeColor(mode.key, order) }} />
          <div>
            <b>{i === 0 ? "Usual answer" : mode.key === MALFORMED ? "Malformed output" : `Mode ${i + 1}`}</b>
            <div className="dim small">{signatureText(mode.signature)}</div>
            <code>{mode.representative}</code>
            <div className="bar">
              <i style={{ width: pct(mode.share), background: modeColor(mode.key, order) }} />
            </div>
          </div>
          <span className="num">
            {pct(mode.share)}
            <span className="dim small"> · {mode.count}</span>
          </span>
        </div>
      ))}
    </div>
  );
}

/**
 * Mode topology of one cell: each run is a column, split by the share of answers in each
 * mode. A flat single colour is one behaviour. A second band that keeps coming back is
 * a second behaviour, even when the decision field never changed.
 */
export function ModeRiver({ cell, noiseFloor }: { cell: ModeCell; noiseFloor: number }) {
  const runs = cell.by_run;
  // Pooled modes first, so the usual answer keeps the trace colour. Then any mode that
  // appears only in runs older than the pooled window: dropping it would leave that run's
  // column short of 100% with no sign of why.
  const pooledKeys = cell.pooled.modes.map((m) => m.key);
  const olderKeys = [...new Set(runs.flatMap((run) => Object.keys(run.shares)))].filter(
    (key) => !pooledKeys.includes(key),
  );
  const order = [...pooledKeys, ...olderKeys.sort()];
  const plotRight = BOX.width - BOX.right;
  const plotBottom = BOX.height - BOX.bottom;
  const band = (plotRight - BOX.left) / runs.length;
  const y = linear(0, 1, plotBottom, BOX.top);
  const pooled = cell.pooled;
  const second = pooled.modes[1];

  return (
    <div className="card">
      <div className="row spread">
        <span className="label">
          Mode topology · {cell.probe} · {perturbationLabel(cell.perturbation)}
        </span>
        <span className={`badge ${pooled.second_mode_detected ? "block" : "pass"}`}>
          {pooled.second_mode_detected ? "second mode detected" : pooled.modes.length > 1 ? "stray answers only" : "one mode"}
        </span>
      </div>
      <svg className="chart" viewBox={`0 0 ${BOX.width} ${BOX.height}`} role="img" aria-label={`mode shares per run for ${cell.probe}`}>
        {[0, 0.5, 1].map((tick) => (
          <g key={tick}>
            <line className="grid-line" x1={BOX.left} x2={plotRight} y1={round(y(tick))} y2={round(y(tick))} />
            <text x={BOX.left - 6} y={round(y(tick)) + 3} textAnchor="end">
              {pct(tick, 0)}
            </text>
          </g>
        ))}
        {runs.map((run, i) =>
          stack(run.shares, order).map((segment) =>
            segment.y1 > segment.y0 ? (
              <rect
                key={`${run.run_id}-${segment.key}`}
                data-mode={segment.key}
                x={round(BOX.left + i * band + 1)}
                width={round(Math.max(band - 2, 1))}
                y={round(y(segment.y1))}
                height={round(y(segment.y0) - y(segment.y1))}
                fill={modeColor(segment.key, order)}
                opacity={segment.key === order[0] ? 0.55 : 0.95}
              >
                <title>
                  run t={run.t}: {pct(segment.y1 - segment.y0)} of {run.n}
                </title>
              </rect>
            ) : null,
          ),
        )}
        <text x={BOX.left} y={BOX.height - 6}>
          t = {runs[0]?.t}
        </text>
        <text x={plotRight} y={BOX.height - 6} textAnchor="end">
          t = {runs[runs.length - 1]?.t}
        </text>
      </svg>
      <p className={pooled.second_mode_detected ? "msg err" : "msg dim"}>
        {second
          ? `Pooled over the last ${cell.window} runs (${pooled.n} samples): the second mode holds ${pct(pooled.second_mode_share)}. ` +
            `Wilson 95% lower bound ${pct(pooled.second_mode_low)}. ` +
            (pooled.second_mode_detected
              ? `That clears the ${pct(noiseFloor, 0)} noise floor: this is a second behaviour, not a stray answer.`
              : `That does not clear the ${pct(noiseFloor, 0)} noise floor.`)
          : `Pooled over the last ${cell.window} runs (${pooled.n} samples): every answer has the same signature.`}
      </p>
      <ModeList modes={pooled.modes} order={order} />
      {olderKeys.length ? (
        <p className="msg dim">
          {olderKeys.length} more mode{olderKeys.length === 1 ? "" : "s"} appear only in runs before the last {cell.window}{" "}
          and are drawn in the chart without a legend entry.
        </p>
      ) : null}
    </div>
  );
}
