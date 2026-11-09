"""Judge panel: calibrate each judge against labelled anchors, quarantine the ones that
stop agreeing, and take a panel verdict only from the judges still in good standing.

A model that scores other models is a measuring instrument, and an instrument is only
trusted while it agrees with a known standard. The standard here is an anchor set: items
a person labelled. Everything in this module is arithmetic over (judge verdict, anchor
label) pairs. No judge is asked whether it is a good judge.

A quarantined judge is not deleted and not overruled quietly. Its vote is excluded, the
exclusion is named in the verdict, and a panel left without a quorum returns no verdict
at all: an unjudged item is reported as unjudged, never as passed.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .charts import PChart
from .golden import wilson

AGREEMENT_FLOOR = 0.8      # below this share of anchors agreed, a judge is not trusted
DRIFT_BASELINE = 8         # calibration rounds needed before drift can be called
DEFAULT_QUORUM = 2


@dataclass(frozen=True)
class Agreement:
    n: int
    agree: int
    rate: float
    low: float             # Wilson 95% interval on the agreement rate
    high: float
    kappa: float           # Cohen's kappa: agreement beyond what the label mix gives by chance


@dataclass(frozen=True)
class PanelVerdict:
    label: str | None      # None = no verdict (tie, or fewer active judges than the quorum)
    counted: tuple[str, ...]
    excluded: tuple[str, ...]
    reason: str


def load_anchors(path: Path) -> dict[str, str]:
    """Anchor id -> label, from every item of the set that carries a `gold_label`."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    items = data["items"] if isinstance(data, dict) else data
    anchors = {i["id"]: i["gold_label"] for i in items if "gold_label" in i}
    if not anchors:
        raise ValueError(f"anchor set has no labelled items: {path}")
    return anchors


def _kappa(pairs: list[tuple[str, str]]) -> float:
    n = len(pairs)
    observed = sum(1 for a, b in pairs if a == b) / n
    labels = {label for pair in pairs for label in pair}
    expected = sum(
        (sum(1 for a, _ in pairs if a == label) / n) * (sum(1 for _, b in pairs if b == label) / n)
        for label in labels
    )
    if expected == 1.0:
        # One label on both sides: chance agreement is total, so kappa is undefined.
        # Report full agreement as 1.0 rather than dividing by zero.
        return 1.0
    return (observed - expected) / (1.0 - expected)


def agreement(verdicts: dict[str, str], anchors: dict[str, str]) -> Agreement:
    """Score one judge's verdicts against the anchors it was shown."""
    unknown = sorted(set(verdicts) - set(anchors))
    if unknown:
        raise ValueError(f"verdicts for ids not in the anchor set: {unknown}")
    if not verdicts:
        raise ValueError("a calibration round needs at least one verdict")
    pairs = [(verdicts[i], anchors[i]) for i in sorted(verdicts)]
    agree = sum(1 for a, b in pairs if a == b)
    rate, low, high = wilson(agree, len(pairs))
    return Agreement(n=len(pairs), agree=agree, rate=rate, low=low, high=high, kappa=_kappa(pairs))


def quarantine(history: list[float], n: int, floor: float = AGREEMENT_FLOOR) -> tuple[bool, str | None]:
    """Decide from a judge's agreement rates, oldest first, whether its vote counts.

    below_floor  the latest round agreed with too few anchors.
    drift        the judge was fine and has moved: with DRIFT_BASELINE earlier rounds on
                 record, the latest rate falls under the p-chart lower limit of that
                 baseline. A judge can clear the floor and still have drifted.
    """
    if not history:
        raise ValueError("no calibration rounds to judge")
    latest = history[-1]
    if latest < floor:
        return True, "below_floor"
    baseline = history[:-1][-DRIFT_BASELINE:]
    if len(baseline) >= DRIFT_BASELINE and n >= 2 and latest < PChart(baseline, n).lcl:
        return True, "drift"
    return False, None


def panel_verdict(votes: dict[str, str], quarantined: set[str],
                  quorum: int = DEFAULT_QUORUM) -> PanelVerdict:
    """Majority label among the judges not in quarantine."""
    counted = tuple(sorted(j for j in votes if j not in quarantined))
    excluded = tuple(sorted(j for j in votes if j in quarantined))
    if len(counted) < quorum:
        return PanelVerdict(None, counted, excluded,
                            f"{len(counted)} active judge(s), quorum is {quorum}")
    tally: dict[str, int] = {}
    for judge in counted:
        tally[votes[judge]] = tally.get(votes[judge], 0) + 1
    ranked = sorted(tally.items(), key=lambda kv: (-kv[1], kv[0]))
    if len(ranked) > 1 and ranked[0][1] == ranked[1][1]:
        return PanelVerdict(None, counted, excluded,
                            f"tie between '{ranked[0][0]}' and '{ranked[1][0]}'")
    label, count = ranked[0]
    return PanelVerdict(label, counted, excluded, f"{count} of {len(counted)} active judges")
