"""Golden-defect suite: an operating curve for the instrument, not a pass line.

The detector and this benchmark were written by the same hand, so a row of perfect scores
would mean the planted defects were easy, not that the detector is flawless. This suite
therefore sizes defects in units of the healthy process's own standard deviation and sweeps
from far below the detection limit (0.25 sigma) to far above it (3 sigma). The published
result is a curve with misses in it. The misses are the credibility.

Sigma calibration
-----------------
The monitored statistic is the per-point flip rate over N_SAMPLES Bernoulli draws at the
healthy rate HEALTHY_FLIP_P, so its standard deviation is analytic:

    sigma = sqrt(p0 * (1 - p0) / N_SAMPLES)

A "k sigma" cell plants a process whose flip probability is p0 + k * sigma. That is a real
shift of the process mean, expressed in the noise units of the healthy process, which is what
a control chart is built to detect.

Determinism: every cell is seeded, and the healthy baseline for a given seed is identical
across cells (it is the same StableSUT with the same seed), so it is computed once and
reused. That is a caching optimization, not a statistical shortcut.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from statistics import median

from .canonicalize import canonicalize
from .charts import IndividualsChart, PChart
from .contracts import Perturbation, PlanEntry
from .embedding import HashingEmbedder
from .sampler import collect
from .suts import SUT, DriftSUT, FlakySUT, JumpSUT, StableSUT

BASELINE_W = 30          # healthy points establishing the control limits
RUN_T = 40               # monitored points after the baseline window
N_SAMPLES = 40           # Bernoulli draws per monitored point
ONSET = 15               # defect onset, as a monitored-point index
RUNS_PER_CELL = 30       # >= 30 so a rate carries a usable confidence interval
HEALTHY_FLIP_P = 0.04    # the healthy process: a real, non-zero background flip rate
Z95 = 1.959964

# Swept magnitudes. The low end is deliberately below what a 3-sigma chart can see.
SHIFT_SIGMAS = [0.25, 0.5, 1.0, 1.5, 2.0, 3.0]
FLAKE_RATES = [0.01, 0.02, 0.05, 0.10, 0.20]
DRIFT_SIGMAS = [1.0, 2.0, 3.0]      # gradual ramps, same units


def sigma_healthy() -> float:
    """Standard deviation of the monitored flip-rate statistic under the healthy process."""
    return math.sqrt(HEALTHY_FLIP_P * (1.0 - HEALTHY_FLIP_P) / N_SAMPLES)


def flip_p_for_sigma(k: float) -> float:
    """The flip probability whose mean sits k sigma above the healthy mean."""
    return min(1.0, HEALTHY_FLIP_P + k * sigma_healthy())


def wilson(successes: int, n: int) -> tuple[float, float, float]:
    """Wilson score interval: (point, low, high) at 95%. Sane at 0 and at n."""
    if n == 0:
        raise ValueError("wilson() called with zero trials — a rate over no samples")
    p = successes / n
    denom = 1.0 + Z95 * Z95 / n
    centre = (p + Z95 * Z95 / (2 * n)) / denom
    half = Z95 * math.sqrt(p * (1 - p) / n + Z95 * Z95 / (4 * n * n)) / denom
    return p, max(0.0, centre - half), min(1.0, centre + half)


@dataclass
class ScenarioResult:
    cell: str
    seed: int
    alarms: list[int] = field(default_factory=list)
    points: int = 0

    def latency(self) -> int | None:
        post = [t for t in self.alarms if t >= ONSET]
        return (post[0] - ONSET) if post else None

    def detected(self) -> bool:
        return self.latency() is not None


def _entry() -> PlanEntry:
    return PlanEntry(
        probe_id="golden", perturbation=Perturbation.repeat_run,
        invariant_fields=["eligibility_decision"], samples=N_SAMPLES, configs=1,
    )


# The statistical cells are measured on the flip rate and the malformed rate only. Passing an
# empty wording field skips semantic variance (and therefore the embedder) in this hot loop;
# the embedder identity still governs the paraphrase back-check and is recorded in the report.
_EMBEDDER = HashingEmbedder()


def _metric_point(sut: SUT, t: int, seed: int) -> tuple[float, float]:
    samples = collect(_entry(), "golden probe input", sut, t=t, seed=seed)
    m = canonicalize(samples, ["eligibility_decision"], [], "", _EMBEDDER)
    return m.flip_rate["eligibility_decision"], m.malformed_rate


_BASELINE_CACHE: dict[int, tuple[list[float], list[float]]] = {}


def _baseline(seed: int) -> tuple[list[float], list[float]]:
    """Healthy baseline for a seed. Identical across cells by construction, so cache it."""
    if seed not in _BASELINE_CACHE:
        healthy = StableSUT(base_flip_p=HEALTHY_FLIP_P)
        flips, mals = [], []
        for t in range(BASELINE_W):
            f, m = _metric_point(healthy, t, seed)
            flips.append(f)
            mals.append(m)
        _BASELINE_CACHE[seed] = (flips, mals)
    return _BASELINE_CACHE[seed]


def _sut_for(cell: str) -> SUT:
    kind, _, arg = cell.partition(":")
    if kind == "null":
        return StableSUT(base_flip_p=HEALTHY_FLIP_P)
    if kind == "shift":
        return JumpSUT(onset=BASELINE_W + ONSET, flip_rate=flip_p_for_sigma(float(arg)),
                       base_flip_p=HEALTHY_FLIP_P)
    if kind == "drift":
        return DriftSUT(onset=BASELINE_W + ONSET, peak_flip_rate=flip_p_for_sigma(float(arg)),
                        ramp=10, base_flip_p=HEALTHY_FLIP_P)
    if kind == "flake":
        return FlakySUT(onset=BASELINE_W + ONSET, p=float(arg), burst=RUN_T,
                        base_flip_p=HEALTHY_FLIP_P)
    raise ValueError(f"unknown cell kind {kind!r}")


def run_scenario(cell: str, seed: int) -> ScenarioResult:
    base_flip, base_mal = _baseline(seed)
    xchart = IndividualsChart(base_flip)
    pchart = PChart(base_mal, n=N_SAMPLES)
    sut = _sut_for(cell)

    result = ScenarioResult(cell=cell, seed=seed)
    for i in range(RUN_T):
        f, m = _metric_point(sut, BASELINE_W + i, seed)
        result.points += 1
        if xchart.add(BASELINE_W + i, f).alarm or pchart.add(BASELINE_W + i, m).alarm:
            result.alarms.append(i)
    return result


@dataclass
class CellSummary:
    cell: str
    label: str
    runs: int
    detections: int
    sensitivity: float
    ci_low: float
    ci_high: float
    latency_median: float | None
    alarm_points: int
    total_points: int


def summarize(cell: str, label: str, results: list[ScenarioResult]) -> CellSummary:
    runs = len(results)
    if runs == 0:
        raise ValueError(f"cell {cell!r} produced zero runs — refusing to compute a rate")
    total_points = sum(r.points for r in results)
    if total_points == 0:
        raise ValueError(f"cell {cell!r} produced zero monitored points — vacuous cell")
    det = sum(1 for r in results if r.detected())
    p, lo, hi = wilson(det, runs)
    lat = [r.latency() for r in results if r.latency() is not None]
    return CellSummary(
        cell=cell, label=label, runs=runs, detections=det, sensitivity=p,
        ci_low=lo, ci_high=hi, latency_median=(median(lat) if lat else None),
        alarm_points=sum(len(r.alarms) for r in results), total_points=total_points,
    )


def _svg_curve(shift_cells: list[CellSummary], far: float) -> str:
    """Operating curve as a committed SVG: sensitivity against defect magnitude."""
    w, h, pad = 640, 360, 56
    xs = [float(c.cell.split(":")[1]) for c in shift_cells]
    x0, x1 = min(xs), max(xs)

    def px(x): return pad + (x - x0) / (x1 - x0) * (w - 2 * pad)
    def py(y): return h - pad - y * (h - 2 * pad)

    pts = " ".join(f"{px(x):.1f},{py(c.sensitivity):.1f}" for x, c in zip(xs, shift_cells))
    band = ("".join(
        f'<line x1="{px(x):.1f}" y1="{py(c.ci_low):.1f}" x2="{px(x):.1f}" '
        f'y2="{py(c.ci_high):.1f}" stroke="#94a3b8" stroke-width="2"/>'
        for x, c in zip(xs, shift_cells)))
    dots = "".join(f'<circle cx="{px(x):.1f}" cy="{py(c.sensitivity):.1f}" r="4" '
                   f'fill="#0f766e"/>' for x, c in zip(xs, shift_cells))
    xlabels = "".join(
        f'<text x="{px(x):.1f}" y="{h - pad + 20}" font-size="12" text-anchor="middle" '
        f'fill="#334155">{x:g}</text>' for x in xs)
    ylabels = "".join(
        f'<text x="{pad - 10}" y="{py(v) + 4:.1f}" font-size="12" text-anchor="end" '
        f'fill="#334155">{v:g}</text>'
        + f'<line x1="{pad}" y1="{py(v):.1f}" x2="{w - pad}" y2="{py(v):.1f}" '
          f'stroke="#e2e8f0" stroke-width="1"/>'
        for v in (0, 0.25, 0.5, 0.75, 1.0))
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" \
viewBox="0 0 {w} {h}" role="img" aria-label="Seismograph operating curve">
  <rect width="{w}" height="{h}" fill="#ffffff"/>
  <text x="{w/2}" y="26" font-size="15" text-anchor="middle" fill="#0f172a">\
Seismograph operating curve: detection vs defect magnitude</text>
  <text x="{w/2}" y="44" font-size="11" text-anchor="middle" fill="#64748b">\
{RUNS_PER_CELL} runs per cell, 95% Wilson intervals, false alarm rate {far:.4f} on null cells</text>
  {ylabels}
  <polyline points="{pts}" fill="none" stroke="#0f766e" stroke-width="2"/>
  {band}{dots}{xlabels}
  <text x="{w/2}" y="{h - 10}" font-size="12" text-anchor="middle" fill="#334155">\
planted mean shift (sigma of the healthy process)</text>
  <text x="16" y="{h/2}" font-size="12" text-anchor="middle" fill="#334155" \
transform="rotate(-90 16 {h/2})">sensitivity</text>
</svg>
"""


@dataclass
class SuiteReport:
    shift: list[CellSummary]
    drift: list[CellSummary]
    flake: list[CellSummary]
    null: CellSummary
    false_alarm_rate: float
    far_ci: tuple[float, float]
    detection_floor: float | None
    embedder_id: str
    svg: str
    lines: list[str]

    def render(self) -> str:
        return "\n".join(self.lines) + "\n"


def embedder_identity() -> str:
    """Identity of the embedder in force. A silent embedder change corrupts every baseline,
    so it is recorded in every report and checked against the stored baseline."""
    dim = len(_EMBEDDER.embed(["dimension probe"])[0])
    return f"{_EMBEDDER.name}/dim={dim}/v1"


def run_suite(runs_per_cell: int = RUNS_PER_CELL) -> SuiteReport:
    if runs_per_cell < 30:
        raise ValueError("runs_per_cell < 30: a rate without a usable interval is not a result")
    seeds = list(range(100, 100 + runs_per_cell))
    sig = sigma_healthy()

    shift = [summarize(f"shift:{k}", f"abrupt {k:g} sigma",
                       [run_scenario(f"shift:{k}", s) for s in seeds])
             for k in SHIFT_SIGMAS]
    drift = [summarize(f"drift:{k}", f"gradual ramp to {k:g} sigma",
                       [run_scenario(f"drift:{k}", s) for s in seeds])
             for k in DRIFT_SIGMAS]
    flake = [summarize(f"flake:{p}", f"format flake {p:.0%}",
                       [run_scenario(f"flake:{p}", s) for s in seeds])
             for p in FLAKE_RATES]
    null = summarize("null", "no planted defect",
                     [run_scenario("null", s) for s in seeds])

    far = null.alarm_points / null.total_points
    _, far_lo, far_hi = wilson(null.alarm_points, null.total_points)

    floor = next((float(c.cell.split(":")[1]) for c in shift if c.ci_low >= 0.80), None)

    lines = [
        "# Seismograph operating curve",
        "",
        f"embedder: `{embedder_identity()}`",
        f"healthy process: flip p={HEALTHY_FLIP_P}, n={N_SAMPLES}/point, "
        f"sigma={sig:.4f} (analytic)",
        f"design: baseline {BASELINE_W} points, monitored {RUN_T}, onset K={ONSET}, "
        f"{runs_per_cell} runs per cell, 95% Wilson intervals",
        "",
        "## Detection vs defect magnitude (abrupt mean shift)",
        "",
        "| shift | flip p | detected | sensitivity | 95% CI | median latency |",
        "|---|---|---|---|---|---|",
    ]
    for c, k in zip(shift, SHIFT_SIGMAS):
        lat = "-" if c.latency_median is None else f"{c.latency_median:g}"
        lines.append(f"| {k:g} sigma | {flip_p_for_sigma(k):.4f} | {c.detections}/{c.runs} "
                     f"| {c.sensitivity:.2f} | {c.ci_low:.2f}-{c.ci_high:.2f} | {lat} |")

    lines += ["", "## Gradual drift", "",
              "| ramp to | detected | sensitivity | 95% CI | median latency |",
              "|---|---|---|---|---|"]
    for c, k in zip(drift, DRIFT_SIGMAS):
        lat = "-" if c.latency_median is None else f"{c.latency_median:g}"
        lines.append(f"| {k:g} sigma | {c.detections}/{c.runs} | {c.sensitivity:.2f} "
                     f"| {c.ci_low:.2f}-{c.ci_high:.2f} | {lat} |")

    lines += ["", "## Format flake (p-chart)", "",
              "| flake rate | detected | sensitivity | 95% CI | median latency |",
              "|---|---|---|---|---|"]
    for c, p in zip(flake, FLAKE_RATES):
        lat = "-" if c.latency_median is None else f"{c.latency_median:g}"
        lines.append(f"| {p:.0%} | {c.detections}/{c.runs} | {c.sensitivity:.2f} "
                     f"| {c.ci_low:.2f}-{c.ci_high:.2f} | {lat} |")

    lines += [
        "", "## Null cells (no planted defect)", "",
        f"- runs: {null.runs}, monitored points: {null.total_points}",
        f"- alarm points: {null.alarm_points}",
        f"- false alarm rate: **{far:.4f}** (95% CI {far_lo:.4f}-{far_hi:.4f})",
        f"- runs raising at least one false alarm: {null.detections}/{null.runs}",
        "",
        "## What this instrument detects, and what it misses",
        "",
        ("- Detection floor (lower CI bound >= 0.80): "
         + (f"**{floor:g} sigma**" if floor is not None
            else "**not reached within the swept range**")),
        "- Everything below that magnitude is a documented miss, listed in the table above.",
        "",
        "![operating curve](eval_curve.svg)",
    ]

    return SuiteReport(shift=shift, drift=drift, flake=flake, null=null,
                       false_alarm_rate=far, far_ci=(far_lo, far_hi),
                       detection_floor=floor, embedder_id=embedder_identity(),
                       svg=_svg_curve(shift, far), lines=lines)


# --------------------------------------------------------------------------- acceptance
# Bounds are stated on the parts of the curve an instrument must get right, NOT on every
# cell: demanding detection at 0.25 sigma would be demanding the impossible, and demanding
# zero false alarms would be demanding a chart that never speaks.
FAR_BOUND = 0.03
LARGE_SHIFT_SENSITIVITY = 0.90     # at 3 sigma
LARGE_FLAKE_SENSITIVITY = 0.90     # at 20%
MONOTONIC_TOLERANCE = 0.10         # sensitivity must not fall as magnitude rises


def acceptance(r: SuiteReport) -> list[tuple[str, str, bool]]:
    """(check, observed, passed) — the bounds that gate a release."""
    big = r.shift[-1]
    big_flake = r.flake[-1]
    checks = [
        (f"sensitivity at {SHIFT_SIGMAS[-1]:g} sigma >= {LARGE_SHIFT_SENSITIVITY}",
         f"{big.sensitivity:.2f}", big.sensitivity >= LARGE_SHIFT_SENSITIVITY),
        (f"sensitivity at {FLAKE_RATES[-1]:.0%} flake >= {LARGE_FLAKE_SENSITIVITY}",
         f"{big_flake.sensitivity:.2f}", big_flake.sensitivity >= LARGE_FLAKE_SENSITIVITY),
        (f"false alarm rate <= {FAR_BOUND}",
         f"{r.false_alarm_rate:.4f}", r.false_alarm_rate <= FAR_BOUND),
        ("sensitivity non-decreasing in magnitude",
         " ".join(f"{c.sensitivity:.2f}" for c in r.shift),
         all(b.sensitivity >= a.sensitivity - MONOTONIC_TOLERANCE
             for a, b in zip(r.shift, r.shift[1:]))),
        ("every cell computed from a non-zero sample count",
         f"{sum(c.total_points for c in r.shift + r.drift + r.flake + [r.null])} points",
         all(c.total_points > 0 and c.runs >= 30
             for c in r.shift + r.drift + r.flake + [r.null])),
    ]
    return checks


def thresholds_met(r: SuiteReport) -> bool:
    return all(ok for _, _, ok in acceptance(r))
