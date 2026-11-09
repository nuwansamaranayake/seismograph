"""Canonicalizer: reduce a sample distribution to consistency metrics.

Everything here is deterministic arithmetic over the samples. The dangerous failure is not
noise but a hidden second mode, so the flip rate is measured against the modal value, and
semantic variance is measured pairwise — averages conceal, distributions reveal.
"""
from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations

from .embedding import Embedder, cosine
from .sampler import Sample


@dataclass(frozen=True)
class CellMetrics:
    probe_id: str
    perturbation: str
    n: int
    malformed_rate: float
    flip_rate: dict[str, float]          # invariant field -> fraction differing from mode
    jaccard_mean: dict[str, float]       # invariant field -> mean pairwise jaccard
    semantic_variance: float             # mean pairwise cosine distance of wording


def _counts(values: list[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for v in values:
        counts[v] = counts.get(v, 0) + 1
    return counts


def _mode_flip_rate(values: list[str]) -> float:
    if not values:
        return 0.0
    return 1.0 - max(_counts(values).values()) / len(values)


def monotonic_violation_rate(rungs: list[list[Sample]], field: str, order: list[str]) -> float:
    """Share of adjacent ladder steps where the field moves AGAINST the declared order.

    Each rung is reduced to its modal value, so within-rung noise is the flip rate's job
    and this number is only about direction. A rung whose modal value is not in `order`
    (or that produced no parseable output) cannot be placed on the scale, so every step
    touching it counts as a violation: an unplaceable answer is not a monotonic one.
    """
    if len(rungs) < 2:
        raise ValueError("monotonicity needs at least two rungs")
    rank = {value: i for i, value in enumerate(order)}
    placed: list[int | None] = []
    for rung in rungs:
        values = [str(s.parsed.get(field)) for s in rung if s.parsed is not None]
        counts = _counts(values)
        # Ties break toward the earlier value in `order`, then alphabetically: stable.
        modal = min(counts, key=lambda v: (-counts[v], rank.get(v, len(rank)), v)) if counts else None
        placed.append(rank.get(modal) if modal is not None else None)
    steps = list(zip(placed, placed[1:], strict=False))
    bad = sum(1 for a, b in steps if a is None or b is None or b < a)
    return bad / len(steps)


def _mean_pairwise_jaccard(sets: list[frozenset]) -> float:
    pairs = list(combinations(sets, 2))
    if not pairs:
        return 1.0
    return sum(_jaccard(a, b) for a, b in pairs) / len(pairs)


def _as_set(value) -> frozenset:
    return frozenset(value or []) if isinstance(value, list) else frozenset()


def _stable_key(value) -> str:
    """Text that is the same in every process. repr() of a frozenset follows hash order,
    which changes with PYTHONHASHSEED, so a tie broken on it could pick a different
    reference in CI than on a laptop."""
    if isinstance(value, frozenset):
        return repr(sorted(map(str, value)))
    return repr(value)


def _modal(values: list):
    """Most common value. Ties break on the value's stable text, so the same samples give
    the same answer in every process."""
    counts = _counts([_stable_key(v) for v in values])
    winner = min(counts, key=lambda k: (-counts[k], k))
    return next(v for v in values if _stable_key(v) == winner)


def _jaccard(a: frozenset, b: frozenset) -> float:
    union = a | b
    return (len(a & b) / len(union)) if union else 1.0


def canonicalize(
    samples: list[Sample],
    equal_fields: list[str],
    jaccard_fields: list[str],
    wording_field: str,
    embedder: Embedder,
    reference: list[Sample] | None = None,
) -> CellMetrics:
    """Reduce one cell to its metrics.

    Without `reference` the cell is judged against itself: flip rate is the share that
    differs from the cell's own modal value. That is right for repeat_run.

    A perturbed cell is different. If every variant is wrong in the same way, the cell
    agrees with itself perfectly. So a metamorphic cell passes `reference`, the samples
    of the unperturbed seed, and each variant is compared with the seed's modal answer.
    """
    if not samples:
        raise ValueError("cannot canonicalize an empty sample set")
    declared = equal_fields + jaccard_fields

    def usable(group: list[Sample]) -> list[dict]:
        """The outputs that can be read against the contract. Malformed means the output
        is not a JSON object, or it lacks a field the cell's invariants name. Without the
        second half a contract with a misspelt field compares None with None on every
        sample and passes every system put in front of it."""
        return [s.parsed for s in group
                if s.parsed is not None and all(f in s.parsed for f in declared)]

    parsed = usable(samples)
    malformed_rate = 1.0 - len(parsed) / len(samples)
    ref = usable(reference or [])

    flip_rate: dict[str, float]
    jaccard_mean: dict[str, float]
    if not parsed or (reference is not None and not ref):
        # Nothing here can be compared: every sample is malformed, or the seed is. Report
        # the invariant as fully violated rather than as unmeasured. The malformed rate
        # carries the cause, and a quiet 0.0 would read as a pass over nothing even
        # under a contract that tolerates malformed output.
        flip_rate = {f: 1.0 for f in equal_fields}
        jaccard_mean = {f: 0.0 for f in jaccard_fields}
    elif ref:
        flip_rate = {}
        jaccard_mean = {}
        for f in equal_fields:
            expected = _modal([str(p.get(f)) for p in ref])
            differing = sum(1 for p in parsed if str(p.get(f)) != expected)
            flip_rate[f] = differing / len(parsed)
        for f in jaccard_fields:
            expected_set = _modal([_as_set(p.get(f)) for p in ref])
            scores = [_jaccard(_as_set(p.get(f)), expected_set) for p in parsed]
            jaccard_mean[f] = sum(scores) / len(scores)
    else:
        flip_rate = {
            f: _mode_flip_rate([str(p.get(f)) for p in parsed]) for f in equal_fields
        }
        jaccard_mean = {
            f: _mean_pairwise_jaccard([_as_set(p.get(f)) for p in parsed])
            for f in jaccard_fields
        }

    wordings = [str(p.get(wording_field, "")) for p in parsed if p.get(wording_field)]
    semantic_variance = 0.0
    if len(wordings) >= 2:
        vecs = embedder.embed(wordings)
        dists = [1.0 - cosine(a, b) for a, b in combinations(vecs, 2)]
        semantic_variance = sum(dists) / len(dists)

    first = samples[0]
    return CellMetrics(
        probe_id=first.probe_id,
        perturbation=first.perturbation,
        n=len(samples),
        malformed_rate=malformed_rate,
        flip_rate=flip_rate,
        jaccard_mean=jaccard_mean,
        semantic_variance=semantic_variance,
    )
