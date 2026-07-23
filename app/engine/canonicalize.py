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


def _mode_flip_rate(values: list[str]) -> float:
    if not values:
        return 0.0
    counts: dict[str, int] = {}
    for v in values:
        counts[v] = counts.get(v, 0) + 1
    modal = max(counts.values())
    return 1.0 - modal / len(values)


def _mean_pairwise_jaccard(sets: list[frozenset]) -> float:
    pairs = list(combinations(sets, 2))
    if not pairs:
        return 1.0
    total = 0.0
    for a, b in pairs:
        union = a | b
        total += (len(a & b) / len(union)) if union else 1.0
    return total / len(pairs)


def canonicalize(
    samples: list[Sample],
    equal_fields: list[str],
    jaccard_fields: list[str],
    wording_field: str,
    embedder: Embedder,
) -> CellMetrics:
    if not samples:
        raise ValueError("cannot canonicalize an empty sample set")
    parsed = [s.parsed for s in samples if s.parsed is not None]
    malformed_rate = 1.0 - len(parsed) / len(samples)

    flip_rate = {
        f: _mode_flip_rate([str(p.get(f)) for p in parsed]) for f in equal_fields
    }
    jaccard_mean = {
        f: _mean_pairwise_jaccard(
            [frozenset(p.get(f) or []) if isinstance(p.get(f), list) else frozenset() for p in parsed]
        )
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
