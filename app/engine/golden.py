"""Golden-defect suite: measure the instrument against defects planted at known onsets.

Each scenario simulates a monitored metric stream: at every time step the sampler collects
N outputs from a SUT, the canonicalizer reduces them to a metric point, and the charts judge
it. Because onset K is known, detection latency, sensitivity, and false alarms are computed
exactly — not argued. Deterministic given the seed set and the HashingEmbedder.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from statistics import median

from .canonicalize import canonicalize
from .charts import IndividualsChart, PChart
from .contracts import Perturbation, PlanEntry
from .embedding import HashingEmbedder
from .sampler import collect
from .suts import SUT, DriftSUT, FlakySUT, JumpSUT, StableSUT

BASELINE_W = 30
RUN_T = 60          # monitored points after the baseline window
N_SAMPLES = 20
ONSET = 15          # defect onset, in monitored-point index


@dataclass
class ScenarioResult:
    kind: str            # clean | jump | drift | flake
    seed: int
    alarms: list[int] = field(default_factory=list)   # monitored-point indexes with alarms

    def latency(self) -> int | None:
        post = [t for t in self.alarms if t >= ONSET]
        return (post[0] - ONSET) if post else None


def _entry() -> PlanEntry:
    return PlanEntry(
        probe_id="golden", perturbation=Perturbation.repeat_run,
        invariant_fields=["eligibility_decision"], samples=N_SAMPLES, configs=1,
    )


def _metric_point(sut: SUT, t: int, seed: int) -> tuple[float, float]:
    """(flip_rate, malformed_rate) at time t."""
    samples = collect(_entry(), "golden probe input", sut, t=t, seed=seed)
    m = canonicalize(samples, ["eligibility_decision"], [], "response_wording",
                     HashingEmbedder())
    return m.flip_rate["eligibility_decision"], m.malformed_rate


def run_scenario(kind: str, seed: int) -> ScenarioResult:
    if kind == "clean":
        sut: SUT = StableSUT()
    elif kind == "jump":
        sut = JumpSUT(onset=BASELINE_W + ONSET, flip_rate=0.35)
    elif kind == "drift":
        sut = DriftSUT(onset=BASELINE_W + ONSET, peak_flip_rate=0.35, ramp=10)
    elif kind == "flake":
        sut = FlakySUT(onset=BASELINE_W + ONSET, p=0.15, burst=15)
    else:
        raise ValueError(f"unknown scenario kind {kind!r}")

    baseline_flip, baseline_mal = [], []
    for t in range(BASELINE_W):
        f, m = _metric_point(StableSUT(), t, seed)      # baseline is always healthy
        baseline_flip.append(f)
        baseline_mal.append(m)
    xchart = IndividualsChart(baseline_flip)
    pchart = PChart(baseline_mal, n=N_SAMPLES)

    result = ScenarioResult(kind=kind, seed=seed)
    for i in range(RUN_T):
        f, m = _metric_point(sut, BASELINE_W + i, seed)
        if xchart.add(BASELINE_W + i, f).alarm or pchart.add(BASELINE_W + i, m).alarm:
            result.alarms.append(i)
    return result


@dataclass
class SuiteReport:
    jump_latency_median: float | None
    drift_latency_median: float | None
    sensitivity: float
    false_alarm_rate: float
    flake_detection: float
    rows: list[str]

    def render(self) -> str:
        out = ["# Seismograph golden-defect eval report", ""]
        out += self.rows
        return "\n".join(out) + "\n"


def run_suite(n_per_kind: int = 20) -> SuiteReport:
    seeds = list(range(100, 100 + n_per_kind))
    clean = [run_scenario("clean", s) for s in seeds]
    jump = [run_scenario("jump", s) for s in seeds]
    drift = [run_scenario("drift", s) for s in seeds]
    flake = [run_scenario("flake", s) for s in seeds]

    jl = [r.latency() for r in jump if r.latency() is not None]
    dl = [r.latency() for r in drift if r.latency() is not None]
    planted = jump + drift + flake
    detected = sum(1 for r in planted if r.latency() is not None)
    sensitivity = detected / len(planted)
    clean_alarm_points = sum(len(r.alarms) for r in clean)
    false_alarm_rate = clean_alarm_points / (len(clean) * RUN_T)
    flake_detected = sum(1 for r in flake if r.latency() is not None) / len(flake)

    report = SuiteReport(
        jump_latency_median=median(jl) if jl else None,
        drift_latency_median=median(dl) if dl else None,
        sensitivity=sensitivity,
        false_alarm_rate=false_alarm_rate,
        flake_detection=flake_detected,
        rows=[],
    )
    report.rows = [
        f"scenarios per kind: {n_per_kind}  (baseline {BASELINE_W}, monitored {RUN_T}, "
        f"n {N_SAMPLES}, onset K={ONSET})",
        "",
        "| metric | value | bound | pass |",
        "|---|---|---|---|",
        _row("jump latency median", report.jump_latency_median, "<= 3",
             report.jump_latency_median is not None and report.jump_latency_median <= 3),
        _row("drift latency median", report.drift_latency_median, "<= 10",
             report.drift_latency_median is not None and report.drift_latency_median <= 10),
        _row("sensitivity", round(sensitivity, 4), ">= 0.90", sensitivity >= 0.90),
        _row("false alarm rate", round(false_alarm_rate, 4), "<= 0.01",
             false_alarm_rate <= 0.01),
        _row("flake detection", round(flake_detected, 4), ">= 0.90", flake_detected >= 0.90),
    ]
    return report


def _row(name: str, value, bound: str, ok: bool) -> str:
    return f"| {name} | {value} | {bound} | {'PASS' if ok else 'FAIL'} |"


def thresholds_met(r: SuiteReport) -> bool:
    return (
        r.jump_latency_median is not None and r.jump_latency_median <= 3
        and r.drift_latency_median is not None and r.drift_latency_median <= 10
        and r.sensitivity >= 0.90
        and r.false_alarm_rate <= 0.01
        and r.flake_detection >= 0.90
    )
