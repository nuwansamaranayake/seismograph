// Shapes the API returns. One block per row of contracts.md.

export type Decision = "pass" | "block";

export interface LatestGate {
  run_id: number;
  decision: Decision;
  worst_flip_rate: number;
  threshold: number;
  t: number;
  sut: string;
  reasons: string[];
  created_at: string | null;
}

export interface ContractSummary {
  name: string;
  subject: string;
  plan_id: string;
  created_at: string | null;
  runs: number;
  latest: LatestGate | null;
  chart_warm: boolean;
  alarms: number;
  latest_point_alarm: boolean;
  trend: number[];
}

export interface Overview {
  contracts: number;
  runs: number;
  passing: number;
  blocked: number;
  never_run: number;
  alarms: number;
  cells_with_second_mode: number;
  judges: { total: number; quarantined: number };
  latest: ContractSummary[];
}

export interface ChartPoint {
  t: number;
  value: number;
  center: number;
  ucl: number;
  lcl: number;
  alarm: boolean;
  rule: string | null;
}

export interface Chart {
  warm: boolean;
  baseline_needed: number;
  runs_until_warm: number;
  points: ChartPoint[];
}

export interface SeriesPoint {
  index: number;
  run_id: number;
  t: number;
  sut: string;
  decision: Decision;
  worst_flip_rate: number;
  worst_malformed_rate: number;
  reasons: string[];
  created_at: string | null;
}

export interface Mode {
  key: string;
  count: number;
  share: number;
  signature: Record<string, unknown>;
  representative: string;
}

export interface ModeReport {
  n: number;
  modes: Mode[];
  second_mode_share: number;
  second_mode_low: number;
  second_mode_detected: boolean;
}

export interface ModeCell {
  probe: string;
  perturbation: string;
  window: number;
  pooled: ModeReport;
  by_run: { run_id: number; t: number; n: number; shares: Record<string, number> }[];
}

export interface MatrixRow {
  probe: string;
  perturbation: string;
  n: number;
  flip_rate: number;
  malformed_rate: number;
  jaccard_mean: Record<string, number>;
  semantic_variance: number;
  second_mode_share: number;
  violated: boolean;
}

export interface GatePolicy {
  max_decision_flip_rate: number;
  max_malformed_rate: number;
  max_second_mode_share?: number;
}

export interface Report {
  contract: string;
  subject: string;
  plan_id: string;
  runs: number;
  gate_policy: GatePolicy;
  latest_gate: { decision: Decision; worst_flip_rate: number; threshold: number } | null;
  series: SeriesPoint[];
  charts: { flip: Chart; malformed: Chart };
  mode_noise_floor: number;
  mode_window: number;
  modes: ModeCell[];
  matrix: MatrixRow[];
  notes: string[];
}

export interface Invariant {
  field: string;
  under: string[];
  relation: string;
  threshold?: number;
  order?: string[];
}

export interface ContractDetail {
  name: string;
  subject: string;
  plan_id: string;
  created_at: string | null;
  yaml: string;
  invariants: Invariant[];
  run_policy: { samples: number; configs: number; confidence: number };
  gate: GatePolicy;
  probes: { id: string; input: string; ladder: string[] | null }[];
  plan: { probe_id: string; perturbation: string; invariant_fields: string[]; samples: number }[];
  variants: { probe: string; perturbation: string; text: string; back_check_score: number | null; accepted: boolean }[];
}

export interface Simulator {
  name: string;
  summary: string;
  planted_defect: string | null;
}

export interface RunResult {
  run_id: number;
  cells: number;
  gate: Decision;
  reasons: string[];
  worst_flip_rate: number;
  threshold: number;
  worst_cell: { probe: string; perturbation: string; field: string } | null;
  worst_malformed_rate: number;
  skipped: { probe: string; perturbation: string; reason: string }[];
}

export interface RunDetail {
  run_id: number;
  contract: string;
  t: number;
  seed: number;
  sut: string;
  embedder: string;
  created_at: string | null;
  simulator: { summary: string; planted_defect: string | null } | null;
  gate: {
    decision: Decision;
    worst_flip_rate: number;
    threshold: number;
    evidence: { reasons?: string[]; skipped?: { probe: string; perturbation: string; reason: string }[] };
  } | null;
  matrix: MatrixRow[];
  modes: {
    probe: string;
    perturbation: string;
    n: number;
    modes: Mode[];
    second_mode_share: number;
    second_mode_detected: boolean;
  }[];
}

export interface JudgeRound {
  round: number;
  n: number;
  agree: number;
  rate: number;
  kappa: number;
  quarantined: boolean;
  reason: string | null;
}

export interface JudgeState {
  judge: string;
  rounds: JudgeRound[];
  latest_rate: number;
  latest_kappa: number;
  quarantined: boolean;
  reason: string | null;
}

export interface Judges {
  anchors: { count: number; labels: string[]; ids: string[]; source: string };
  floor: number;
  drift_baseline: number;
  judges: JudgeState[];
}

export interface CalibrationResult extends JudgeRound {
  judge: string;
  low: number;
  high: number;
}

export interface PanelResult {
  label: string | null;
  reason: string;
  counted: string[];
  excluded: string[];
  judges: Record<string, string>;
}

export interface GoldenSummary {
  contract: string;
  model: string | null;
  kind: string | null;
  passed: boolean | null;
  probes: number | null;
  records: number | null;
  run_at: string | null;
  available: string[];
}

export interface CalibrationBin {
  bin: string;
  count: number;
  // null when the bin is empty: there is no accuracy of zero answers
  accuracy: number | null;
  mean_confidence: number | null;
  abs_gap: number | null;
}

export interface GoldenDetail {
  contract: string;
  run: {
    model: string;
    kind: string;
    passed: boolean;
    probes: number;
    records: number;
    samples: number;
    run_at: string;
    latency_ms: { p50: number; p95: number };
    usage: { input_tokens: number; cost_usd: number };
    gate: Record<string, number>;
    metrics: Record<string, unknown>;
  };
  calibration: { points: number; bins: CalibrationBin[]; expected_calibration_error: number } | null;
  drift: {
    model_a: string;
    model_b: string;
    model_a_served: string;
    model_b_served: string;
    overall_agreement: number;
    per_question: Record<string, { agreement_rate: number; n_pairs: number; mean_total_variation: number }>;
    control_chart: { batch_size: number; baseline_points: number; series: number[]; points: ChartPoint[] };
  } | null;
}

export interface VariantsResult {
  accepted: number;
  rejected: number;
  variants: { text: string; back_check_score: number; accepted: boolean; reason: string }[];
}

export interface RegisterResult {
  contract: string;
  plan_id: string;
  entries: number;
}
