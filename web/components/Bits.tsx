import type { ReactNode } from "react";
import { polyline, trace, yCeiling } from "@/lib/scale";
import type { Decision } from "@/lib/types";

export function GateBadge({ decision }: { decision: Decision | null }) {
  if (decision === null) return <span className="badge">no runs</span>;
  return <span className={`badge ${decision}`}>{decision}</span>;
}

/** Every simulated system carries this tag wherever it is named. */
export function SimulatorTag() {
  return (
    <span className="badge sim" title="An in-process simulator with a planted defect. Not a real system.">
      simulator
    </span>
  );
}

export function Stat({
  label,
  value,
  tone,
  note,
}: {
  label: string;
  value: ReactNode;
  tone?: "good" | "bad" | "warn";
  note?: string;
}) {
  return (
    <div className={`card stat ${tone ?? ""}`.trim()}>
      <span className="label">{label}</span>
      <b>{value}</b>
      {note ? <span className="dim small">{note}</span> : null}
    </div>
  );
}

/** The recorder strip: the series drawn as pen swings. An empty series is a flat line. */
export function Strip({ series, label }: { series: number[]; label: string }) {
  const width = 1000;
  const height = 72;
  return (
    <svg className="strip" viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" role="img" aria-label={label}>
      <line className="axis" x1="0" y1={height / 2} x2={width} y2={height / 2} />
      {/* Scaled to the series' own largest value: the strip shows shape, the charts show size. */}
      <polyline points={trace(series, width, height, Math.max(0, ...series))} />
    </svg>
  );
}

export function Sparkline({ series, blocked }: { series: number[]; blocked: boolean }) {
  if (series.length < 2) return <span className="dim mono small">{series.length ? "1 run" : "no runs"}</span>;
  const width = 120;
  const height = 26;
  const top = yCeiling(series, []);
  const points = series.map((v, i): [number, number] => [
    (i / (series.length - 1)) * width,
    height - 2 - (v / top) * (height - 4),
  ]);
  return (
    <svg className={`spark ${blocked ? "block" : ""}`.trim()} viewBox={`0 0 ${width} ${height}`} role="img" aria-label={`worst flip rate over the last ${series.length} runs`}>
      <polyline points={polyline(points)} />
    </svg>
  );
}
