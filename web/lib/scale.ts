// Chart arithmetic, kept apart from the SVG so every number a chart draws is testable.

export interface Box {
  width: number;
  height: number;
  left: number;
  right: number;
  top: number;
  bottom: number;
}

/** Map [d0, d1] onto [r0, r1]. A zero-width domain maps to the middle of the range. */
export function linear(d0: number, d1: number, r0: number, r1: number): (v: number) => number {
  if (d1 === d0) return () => (r0 + r1) / 2;
  return (v) => r0 + ((v - d0) / (d1 - d0)) * (r1 - r0);
}

/** Round up to 1, 2, or 5 times a power of ten: an axis ceiling a person can read. */
export function niceCeil(value: number): number {
  if (!(value > 0)) return 1;
  const magnitude = 10 ** Math.floor(Math.log10(value));
  const unit = value / magnitude;
  const step = unit <= 1 ? 1 : unit <= 2 ? 2 : unit <= 5 ? 5 : 10;
  return Number((step * magnitude).toPrecision(12));
}

/** `count` + 1 evenly spaced ticks from 0 to max. */
export function ticks(max: number, count = 4): number[] {
  return Array.from({ length: count + 1 }, (_, i) => Number(((max * i) / count).toPrecision(12)));
}

export function polyline(points: [number, number][]): string {
  return points.map(([x, y]) => `${round(x)},${round(y)}`).join(" ");
}

export function round(v: number): number {
  return Math.round(v * 100) / 100;
}

/** Axis ceiling for a chart: the largest thing it must show, with headroom. */
export function yCeiling(values: number[], limits: number[]): number {
  const top = Math.max(0, ...values, ...limits);
  return niceCeil(top * 1.15);
}

/**
 * A seismograph trace from a series: each value becomes one swing of the pen, up then
 * down, so a quiet series reads as a near-flat line and a disturbed one as visible
 * motion. Deterministic: the same series always draws the same trace.
 */
export function trace(series: number[], width: number, height: number, ceiling: number): string {
  const mid = height / 2;
  if (series.length === 0) return polyline([[0, mid], [width, mid]]);
  const step = width / series.length;
  const amplitude = linear(0, ceiling || 1, 0, mid - 2);
  const points: [number, number][] = [[0, mid]];
  series.forEach((value, i) => {
    const swing = Math.max(amplitude(Math.min(value, ceiling || 1)), 0.6);
    const x = i * step;
    points.push([x + step * 0.25, mid - swing], [x + step * 0.5, mid + swing * 0.7], [x + step * 0.75, mid - swing * 0.35], [x + step, mid]);
  });
  return polyline(points);
}

/** Stack mode shares into bands for one run: [key, y0, y1] in share units, in key order. */
export function stack(shares: Record<string, number>, order: string[]): { key: string; y0: number; y1: number }[] {
  let acc = 0;
  return order.map((key) => {
    const y0 = acc;
    acc += shares[key] ?? 0;
    return { key, y0, y1: acc };
  });
}
