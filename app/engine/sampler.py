"""Sampler: execute an ExperimentPlan cell against a SUT, N samples at a time step.

Deterministic given (seed, t): the RNG is derived from them, so a run is replayable.
Executing a perturbation with no generator raises loudly — a plan cell is never silently
skipped (Standard 3).
"""
from __future__ import annotations

import json
import random
from dataclasses import dataclass

from .contracts import EXECUTABLE_PERTURBATIONS, Perturbation, PlanEntry
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
    variants (see engine.metamorphic). Other perturbations have no Phase 1 generator.
    """
    if entry.perturbation not in EXECUTABLE_PERTURBATIONS:
        raise NotImplementedError(
            f"perturbation '{entry.perturbation.value}' has no generator yet; "
            "declaring it is legal, executing it is not (lands in Phase 2)"
        )
    if entry.perturbation is Perturbation.paraphrase:
        if not paraphrases:
            raise ValueError("paraphrase cell requires pre-generated, back-checked variants")
        inputs = [paraphrases[i % len(paraphrases)] for i in range(entry.samples)]
    else:
        inputs = [probe_input] * entry.samples

    rng = random.Random((seed, entry.probe_id, entry.perturbation.value, t).__repr__())
    samples = []
    for variant in inputs:
        raw = sut.run(variant, t, rng)
        samples.append(
            Sample(
                probe_id=entry.probe_id,
                perturbation=entry.perturbation.value,
                variant_input=variant,
                raw_output=raw,
                parsed=_parse(raw),
            )
        )
    return samples
