"""Control charts: statistically derived limits, signals instead of opinions.

Individuals chart with limits from a baseline window, alarmed by Western Electric rule 1
(beyond 3 sigma) and a run-of-8 drift rule (8 consecutive points on one side of center).
p-chart for malformed rate with binomial limits. A point outside the limits is a signal,
not an opinion; a healthy stream stays quiet.
"""
from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class ChartPoint:
    t: int
    value: float
    center: float
    ucl: float
    lcl: float
    alarm: bool
    rule: str | None      # "we1" | "run8" | None


class IndividualsChart:
    """X-chart. Baseline window sets center and sigma (moving-range estimate); later points
    are judged against frozen limits — re-baselining is explicit, never silent."""

    def __init__(self, baseline: list[float]):
        if len(baseline) < 8:
            raise ValueError("baseline window needs at least 8 points")
        self.center = sum(baseline) / len(baseline)
        mrs = [abs(b - a) for a, b in zip(baseline, baseline[1:])]
        mr_bar = sum(mrs) / len(mrs) if mrs else 0.0
        self.sigma = mr_bar / 1.128 if mr_bar > 0 else 0.0
        # Floor sigma so a perfectly flat baseline still yields usable limits: treat one
        # part in 1e6 of the center (or 1e-6 absolute) as the minimum resolvable noise.
        floor = max(abs(self.center) * 1e-6, 1e-6)
        self.sigma = max(self.sigma, floor)
        self.ucl = self.center + 3 * self.sigma
        self.lcl = self.center - 3 * self.sigma
        self._side_run = 0
        self._side = 0

    def add(self, t: int, value: float) -> ChartPoint:
        rule = None
        if value > self.ucl or value < self.lcl:
            rule = "we1"
        side = 1 if value > self.center else (-1 if value < self.center else 0)
        if side != 0 and side == self._side:
            self._side_run += 1
        else:
            self._side = side
            self._side_run = 1 if side != 0 else 0
        if rule is None and self._side_run >= 8:
            rule = "run8"
        return ChartPoint(
            t=t, value=value, center=self.center, ucl=self.ucl, lcl=self.lcl,
            alarm=rule is not None, rule=rule,
        )


class PChart:
    """Proportion chart for malformed rate: binomial 3-sigma limits around baseline p-bar."""

    def __init__(self, baseline_rates: list[float], n: int):
        if len(baseline_rates) < 8:
            raise ValueError("baseline window needs at least 8 points")
        if n < 2:
            raise ValueError("p-chart needs sample size n >= 2")
        self.n = n
        self.center = sum(baseline_rates) / len(baseline_rates)
        sigma = math.sqrt(max(self.center * (1 - self.center), 1e-12) / n)
        # Same idea as the X-chart floor: a spotless baseline (p-bar = 0) must not make any
        # single malformed sample an alarm; require exceeding what one flake would produce.
        self.ucl = min(1.0, max(self.center + 3 * sigma, 1.5 / n))
        self.lcl = max(0.0, self.center - 3 * sigma)

    def add(self, t: int, rate: float) -> ChartPoint:
        alarm = rate > self.ucl
        return ChartPoint(
            t=t, value=rate, center=self.center, ucl=self.ucl, lcl=self.lcl,
            alarm=alarm, rule="we1" if alarm else None,
        )
