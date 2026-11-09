"""Outcome modes: the shape of a cell's answers, not their average.

A flip rate of 5% can be two very different processes. It can be noise, one stray answer
in twenty with nothing in common. Or it can be a second MODE, a coherent alternative
answer the system reaches again and again by the same route. The average is identical.
The second is a behaviour, and it is the one that grows.

A mode is a distinct signature over the contract's invariant fields. No model and no
embedding is involved: two samples are in the same mode when those fields are equal
(lists compared as sets). Malformed output is a mode of its own.

Detection is a statement about evidence, so it carries an interval: a second mode is
reported as detected only when the Wilson 95% lower bound of its share clears a noise
floor. One odd sample in ten is not a mode. Pooling a window of runs is how a small,
persistent mode becomes visible.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass

from .golden import wilson
from .sampler import Sample

MALFORMED = "malformed"
MODE_NOISE_FLOOR = 0.02


@dataclass(frozen=True)
class Mode:
    key: str               # stable id of the signature: the same mode has the same key in every run
    count: int
    share: float
    signature: dict        # invariant field -> value (lists as sorted lists)
    representative: str    # one raw output from this mode, verbatim


@dataclass(frozen=True)
class ModeReport:
    n: int
    modes: tuple[Mode, ...]            # largest first
    second_mode_share: float           # 0.0 when there is one mode
    second_mode_low: float             # Wilson 95% lower bound of that share
    second_mode_detected: bool

    def to_json(self) -> dict:
        return asdict(self) | {"modes": [asdict(m) for m in self.modes]}


def _signature(parsed: dict, fields: list[str]) -> dict:
    out = {}
    for f in fields:
        value = parsed.get(f)
        out[f] = sorted(set(map(str, value))) if isinstance(value, list) else value
    return out


def _key(signature: dict) -> str:
    text = json.dumps(signature, sort_keys=True, default=str)
    return hashlib.sha256(text.encode()).hexdigest()[:10]


def _report(n: int, tallies: dict[str, dict]) -> ModeReport:
    """tallies: key -> {"count", "signature", "representative"}."""
    ordered = sorted(tallies.items(), key=lambda kv: (-kv[1]["count"], kv[0]))
    modes = tuple(
        Mode(key=key, count=t["count"], share=t["count"] / n,
             signature=t["signature"], representative=t["representative"])
        for key, t in ordered
    )
    second = modes[1] if len(modes) > 1 else None
    low = wilson(second.count, n)[1] if second else 0.0
    return ModeReport(
        n=n, modes=modes,
        second_mode_share=second.share if second else 0.0,
        second_mode_low=low,
        second_mode_detected=low > MODE_NOISE_FLOOR,
    )


def cluster_modes(samples: list[Sample], fields: list[str]) -> ModeReport:
    """Group one cell's samples into modes over the given invariant fields."""
    if not samples:
        raise ValueError("cannot find modes in an empty sample set")
    tallies: dict[str, dict] = {}
    for s in samples:
        if s.parsed is None:
            key, signature = MALFORMED, {}
        else:
            signature = _signature(s.parsed, fields)
            key = _key(signature)
        entry = tallies.setdefault(
            key, {"count": 0, "signature": signature, "representative": s.raw_output})
        entry["count"] += 1
    return _report(len(samples), tallies)


def from_json(data: dict) -> ModeReport:
    return ModeReport(
        n=data["n"],
        modes=tuple(Mode(**m) for m in data["modes"]),
        second_mode_share=data["second_mode_share"],
        second_mode_low=data["second_mode_low"],
        second_mode_detected=data["second_mode_detected"],
    )


def pool(reports: list[ModeReport]) -> ModeReport:
    """Merge the same cell across a window of runs. Modes align on their key."""
    if not reports:
        raise ValueError("nothing to pool")
    tallies: dict[str, dict] = {}
    for report in reports:
        for mode in report.modes:
            entry = tallies.setdefault(
                mode.key, {"count": 0, "signature": mode.signature,
                           "representative": mode.representative})
            entry["count"] += mode.count
    return _report(sum(r.n for r in reports), tallies)
