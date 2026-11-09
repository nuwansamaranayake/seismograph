"""Sampler: execute an ExperimentPlan cell against a SUT, N samples at a time step.

Deterministic given (seed, t): the RNG is derived from them, so a run is replayable.
Executing a perturbation with no generator raises loudly — a plan cell is never silently
skipped (Standard 3).
"""
from __future__ import annotations

import json
import random
from dataclasses import dataclass

from .contracts import Perturbation, PlanEntry
from .perturb import DETERMINISTIC_PERTURBATIONS, variants_for
from .suts import SUT


@dataclass(frozen=True)
class Sample:
    probe_id: str
    perturbation: str
    variant_input: str
    raw_output: str
    parsed: dict | None          # None = malformed output


def _parse(raw: str) -> dict | None:
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return obj if isinstance(obj, dict) else None


def collect(
    entry: PlanEntry,
    probe_input: str,
    sut: SUT,
    t: int,
    seed: int,
    paraphrases: list[str] | None = None,
) -> list[Sample]:
    """Run one plan cell: N samples of the SUT at time t.

    repeat_run reuses the seed input; paraphrase cycles through pre-generated, back-checked
    variants (see engine.metamorphic); irrelevant_context, reordering and format generate
    their variants deterministically (engine.perturb). A monotonic cell is a ladder, not a
    set of variants of one input: use collect_ladder.
    """
    if entry.perturbation is Perturbation.monotonic:
        raise ValueError("a monotonic cell runs over a ladder; use collect_ladder")
    if entry.perturbation is Perturbation.paraphrase:
        if not paraphrases:
            raise ValueError("paraphrase cell requires pre-generated, back-checked variants")
        inputs = [paraphrases[i % len(paraphrases)] for i in range(entry.samples)]
    elif entry.perturbation in DETERMINISTIC_PERTURBATIONS:
        inputs = variants_for(entry.perturbation, probe_input, entry.samples)
    else:
        inputs = [probe_input] * entry.samples

    rng = random.Random((seed, entry.probe_id, entry.perturbation.value, t).__repr__())
    return [_sample(entry, variant, sut, t, rng) for variant in inputs]


def _sample(entry: PlanEntry, variant: str, sut: SUT, t: int, rng: random.Random) -> Sample:
    raw = sut.run(variant, t, rng)
    return Sample(
        probe_id=entry.probe_id,
        perturbation=entry.perturbation.value,
        variant_input=variant,
        raw_output=raw,
        parsed=_parse(raw),
    )


def collect_ladder(
    entry: PlanEntry, ladder: list[str], sut: SUT, t: int, seed: int
) -> list[list[Sample]]:
    """Run a monotonic cell: N samples at every rung of the probe's ladder, in ladder
    order. One RNG for the whole cell, so the run is replayable from (seed, t)."""
    if len(ladder) < 2:
        raise ValueError("a ladder needs at least two rungs")
    rng = random.Random((seed, entry.probe_id, entry.perturbation.value, t).__repr__())
    return [
        [_sample(entry, rung, sut, t, rng) for _ in range(entry.samples)]
        for rung in ladder
    ]
