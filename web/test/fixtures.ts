// Realistic API answers, typed against lib/types.ts so a drifting contract fails tsc.
import type {
  CalibrationBin,
  Chart,
  ChartPoint,
  ContractDetail,
  ContractSummary,
  GoldenDetail,
  GoldenSummary,
  Judges,
  MatrixRow,
  Mode,
  ModeCell,
  Overview,
  Report,
  RunDetail,
  RunResult,
  SeriesPoint,
  Simulator,
} from "@/lib/types";

export function chartPoint(t: number, over: Partial<ChartPoint> = {}): ChartPoint {
  return { t, value: 0.04, center: 0.04, ucl: 0.1, lcl: 0, alarm: false, rule: null, ...over };
}

export function warmChart(over: Partial<Chart> = {}): Chart {
  return {
    warm: true,
    baseline_needed: 8,
    runs_until_warm: 0,
    points: Array.from({ length: 10 }, (_, t) => chartPoint(t)),
    ...over,
  };
}

export function coldChart(over: Partial<Chart> = {}): Chart {
  return { warm: false, baseline_needed: 8, runs_until_warm: 5, points: [], ...over };
}

export function seriesPoint(index: number, over: Partial<SeriesPoint> = {}): SeriesPoint {
  return {
    index,
    run_id: 100 + index,
    t: index,
    sut: "stable",
    decision: "pass",
    worst_flip_rate: 0.04,
    worst_malformed_rate: 0,
    reasons: [],
    created_at: "2026-11-01T10:00:00Z",
    ...over,
  };
}

export function mode(key: string, share: number, over: Partial<Mode> = {}): Mode {
  return {
    key,
    count: Math.round(share * 20),
    share,
    signature: { eligibility_decision: key },
    representative: `Answer for ${key}`,
    ...over,
  };
}

export function modeCell(probe: string, perturbation: string, over: Partial<ModeCell> = {}): ModeCell {
  return {
    probe,
    perturbation,
    window: 3,
    pooled: {
      n: 60,
      modes: [mode("eligible", 1)],
      second_mode_share: 0,
      second_mode_low: 0,
      second_mode_detected: false,
    },
    by_run: [
      { run_id: 100, t: 0, n: 20, shares: { eligible: 1 } },
      { run_id: 101, t: 1, n: 20, shares: { eligible: 1 } },
    ],
    ...over,
  };
}

export function secondModeCell(probe: string, perturbation: string): ModeCell {
  return modeCell(probe, perturbation, {
    pooled: {
      n: 60,
      modes: [mode("eligible", 0.7), mode("denied", 0.3)],
      second_mode_share: 0.3,
      second_mode_low: 0.2,
      second_mode_detected: true,
    },
    by_run: [
      { run_id: 100, t: 0, n: 20, shares: { eligible: 0.7, denied: 0.3 } },
      { run_id: 101, t: 1, n: 20, shares: { eligible: 0.65, denied: 0.35 } },
    ],
  });
}

export function matrixRow(probe: string, perturbation: string, over: Partial<MatrixRow> = {}): MatrixRow {
  return {
    probe,
    perturbation,
    n: 20,
    flip_rate: 0.02,
    malformed_rate: 0,
    second_mode_share: 0,
    jaccard_mean: {},
    semantic_variance: 0,
    violated: false,
    ...over,
  };
}

export function contractSummary(name: string, over: Partial<ContractSummary> = {}): ContractSummary {
  return {
    name,
    subject: "support-agent",
    plan_id: "plan-abc123",
    created_at: "2026-11-01T09:00:00Z",
    runs: 3,
    latest: {
      run_id: 12,
      decision: "pass",
      worst_flip_rate: 0.04,
      threshold: 0.1,
      t: 2,
      sut: "stable",
      reasons: [],
      created_at: "2026-11-01T10:00:00Z",
    },
    chart_warm: true,
    alarms: 0,
    latest_point_alarm: false,
    trend: [0.02, 0.04, 0.03],
    ...over,
  };
}

export function blockedSummary(name: string, over: Partial<ContractSummary> = {}): ContractSummary {
  const latest = contractSummary(name).latest;
  if (!latest) throw new Error("fixture has no latest gate");
  return contractSummary(name, {
    latest: { ...latest, decision: "block", worst_flip_rate: 0.31, sut: "drifting", reasons: ["flip rate over tolerance"] },
    alarms: 2,
    trend: [0.02, 0.1, 0.31],
    ...over,
  });
}

export function overview(over: Partial<Overview> = {}): Overview {
  return {
    contracts: 2,
    runs: 6,
    passing: 1,
    blocked: 1,
    never_run: 0,
    alarms: 2,
    cells_with_second_mode: 1,
    judges: { total: 3, quarantined: 1 },
    latest: [contractSummary("refund-agent"), blockedSummary("triage-bot")],
    ...over,
  };
}

export function report(over: Partial<Report> = {}): Report {
  const series = [
    seriesPoint(0),
    seriesPoint(1),
    seriesPoint(2, { decision: "block", worst_flip_rate: 0.3, reasons: ["flip rate 30.0% over 10.0%"] }),
  ];
  return {
    contract: "refund-agent",
    subject: "support-agent",
    plan_id: "plan-abc123",
    runs: series.length,
    gate_policy: { max_decision_flip_rate: 0.1, max_malformed_rate: 0.05 },
    latest_gate: { decision: "block", worst_flip_rate: 0.3, threshold: 0.1 },
    series,
    charts: { flip: warmChart(), malformed: warmChart() },
    mode_noise_floor: 0.1,
    mode_window: 3,
    modes: [modeCell("refund-basic", "repeat_run")],
    matrix: [matrixRow("refund-basic", "repeat_run")],
    notes: [],
    ...over,
  };
}

export function emptyReport(over: Partial<Report> = {}): Report {
  return report({
    runs: 0,
    latest_gate: null,
    series: [],
    charts: { flip: coldChart(), malformed: coldChart() },
    modes: [],
    matrix: [],
    ...over,
  });
}

export function contractDetail(over: Partial<ContractDetail> = {}): ContractDetail {
  return {
    name: "refund-agent",
    subject: "support-agent",
    plan_id: "plan-abc123",
    created_at: "2026-11-01T09:00:00Z",
    yaml: "contract: refund-agent\nsubject: support-agent\n",
    invariants: [{ field: "eligibility_decision", under: ["repeat_run"], relation: "equal" }],
    run_policy: { samples: 20, configs: 1, confidence: 0.95 },
    gate: { max_decision_flip_rate: 0.1, max_malformed_rate: 0.05 },
    probes: [{ id: "refund-basic", input: "Is a 12 day old blender refundable?", ladder: null }],
    plan: [{ probe_id: "refund-basic", perturbation: "repeat_run", invariant_fields: ["eligibility_decision"], samples: 20 }],
    variants: [],
    ...over,
  };
}

export function paraphraseDetail(over: Partial<ContractDetail> = {}): ContractDetail {
  return contractDetail({
    invariants: [{ field: "eligibility_decision", under: ["repeat_run", "paraphrase"], relation: "equal" }],
    probes: [
      { id: "refund-basic", input: "Is a 12 day old blender refundable?", ladder: null },
      { id: "refund-late", input: "Is a 45 day old blender refundable?", ladder: null },
    ],
    ...over,
  });
}

export function simulators(): Simulator[] {
  return [
    { name: "stable", summary: "Answers the same way every time.", planted_defect: null },
    { name: "drifting", summary: "Starts to flip after t = 4.", planted_defect: "decision flips from t = 4" },
  ];
}

export function runResult(over: Partial<RunResult> = {}): RunResult {
  return {
    run_id: 41,
    cells: 4,
    gate: "pass",
    reasons: [],
    worst_flip_rate: 0.04,
    threshold: 0.1,
    worst_cell: null,
    worst_malformed_rate: 0,
    skipped: [],
    ...over,
  };
}

export function runDetail(over: Partial<RunDetail> = {}): RunDetail {
  return {
    run_id: 41,
    contract: "refund-agent",
    t: 3,
    seed: 7,
    sut: "drifting",
    embedder: "hash-embedder",
    created_at: "2026-11-01T10:00:00Z",
    simulator: { summary: "Starts to flip after t = 4.", planted_defect: "decision flips from t = 4" },
    gate: {
      decision: "block",
      worst_flip_rate: 0.3,
      threshold: 0.1,
      evidence: { reasons: ["flip rate 30.0% over 10.0%"], skipped: [] },
    },
    matrix: [matrixRow("refund-basic", "repeat_run", { flip_rate: 0.3, violated: true })],
    modes: [
      {
        probe: "refund-basic",
        perturbation: "repeat_run",
        n: 20,
        modes: [mode("eligible", 0.7), mode("denied", 0.3)],
        second_mode_share: 0.3,
        second_mode_detected: true,
      },
    ],
    ...over,
  };
}

export function judges(over: Partial<Judges> = {}): Judges {
  return {
    anchors: { count: 12, labels: ["clean", "planted"], ids: ["a1", "a2"], source: "anchors/refunds.json" },
    floor: 0.8,
    drift_baseline: 5,
    judges: [
      {
        judge: "judge-a",
        rounds: [
          { round: 1, n: 12, agree: 11, rate: 0.92, kappa: 0.8, quarantined: false, reason: null },
          { round: 2, n: 12, agree: 12, rate: 1, kappa: 1, quarantined: false, reason: null },
        ],
        latest_rate: 1,
        latest_kappa: 1,
        quarantined: false,
        reason: null,
      },
      {
        judge: "judge-b",
        rounds: [{ round: 1, n: 12, agree: 6, rate: 0.5, kappa: 0.1, quarantined: true, reason: "below_floor" }],
        latest_rate: 0.5,
        latest_kappa: 0.1,
        quarantined: true,
        reason: "below_floor",
      },
    ],
    ...over,
  };
}

export function goldenSummary(contract: string, over: Partial<GoldenSummary> = {}): GoldenSummary {
  return {
    contract,
    model: "model-x",
    kind: "triage",
    passed: true,
    probes: 30,
    records: 90,
    run_at: "2026-11-01T10:00:00Z",
    available: ["run", "calibration", "drift"],
    ...over,
  };
}

export const BINS: CalibrationBin[] = [
  { bin: "0.5-0.7", count: 10, accuracy: 0.5, mean_confidence: 0.6, abs_gap: 0.1 },
  { bin: "0.9-1.0", count: 40, accuracy: 0.97, mean_confidence: 0.95, abs_gap: 0.02 },
];

export function goldenDetail(contract: string, over: Partial<GoldenDetail> = {}): GoldenDetail {
  return {
    contract,
    run: {
      model: "model-x",
      kind: "triage",
      passed: true,
      probes: 30,
      records: 90,
      samples: 3,
      run_at: "2026-11-01T10:00:00Z",
      latency_ms: { p50: 812.4, p95: 1903.7 },
      usage: { input_tokens: 5400, cost_usd: 0.01234 },
      gate: { min_recall: 0.9 },
      metrics: { recall: 0.95, false_positive_rate: 0.02, items_total: 30, label_counts: { clean: 20, planted: 10 } },
    },
    calibration: { points: 50, bins: BINS, expected_calibration_error: 0.045 },
    drift: {
      model_a: "model-x",
      model_b: "model-x-next",
      model_a_served: "model-x-2026-05",
      model_b_served: "model-x-2026-05",
      overall_agreement: 0.9876,
      per_question: {
        is_refund_eligible: { agreement_rate: 0.99, n_pairs: 30, mean_total_variation: 0.0123 },
      },
      control_chart: {
        batch_size: 10,
        baseline_points: 4,
        series: [0.01, 0.02, 0.01, 0.02, 0.01],
        points: [chartPoint(0), chartPoint(1)],
      },
    },
    ...over,
  };
}
