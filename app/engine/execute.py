"""Execute an experiment plan and decide the gate. Pure: no database, no HTTP, no clock.

One function runs every cell of a plan against a system under test and returns the
measurements together with the deterministic gate decision, so the API and the CLI
cannot drift apart on what "block" means.

Cells that cannot run are never silently dropped. A paraphrase cell with no generated
variants is returned in `skipped` with its reason, and a run in which nothing at all was
measured raises: a gate decision over zero measurements would be a recorded pass over
nothing.
"""
from __future__ import annotations

from dataclasses import dataclass

from .canonicalize import CellMetrics, canonicalize, monotonic_violation_rate
from .contracts import Contract, Perturbation, PlanEntry, Relation
from .embedding import Embedder
from .modes import ModeReport, cluster_modes
from .sampler import Sample, collect, collect_ladder
from .suts import SUT


class NothingMeasured(ValueError):
    """The plan had no executable cell."""


@dataclass(frozen=True)
class CellResult:
    metrics: CellMetrics
    modes: ModeReport | None      # None for a monotonic cell: its rungs differ by design


@dataclass(frozen=True)
class RunOutcome:
    cells: tuple[CellResult, ...]
    skipped: tuple[dict, ...]
    decision: str                 # "pass" | "block"
    reasons: tuple[str, ...]      # empty on pass; one line per tripped rule on block
    worst_flip_rate: float
    worst_cell: dict | None       # {"probe", "perturbation", "field"} behind worst_flip_rate
    worst_malformed_rate: float
    jaccard_failures: tuple[dict, ...]
    second_modes: tuple[dict, ...]

    def evidence(self) -> dict:
        return {
            "cells": len(self.cells),
            "skipped": list(self.skipped),
            "reasons": list(self.reasons),
            "worst_cell": self.worst_cell,
            "worst_malformed_rate": self.worst_malformed_rate,
            "jaccard_failures": list(self.jaccard_failures),
            "second_modes": list(self.second_modes),
        }


def _fields(contract: Contract, entry: PlanEntry, relation: Relation) -> list[str]:
    return [i.field for i in contract.invariants
            if i.relation is relation and i.field in entry.invariant_fields
            and entry.perturbation in i.under]


def jaccard_threshold(contract: Contract, field: str, perturbation: str) -> float | None:
    """The threshold declared for this field under this perturbation. Two invariants may
    put different thresholds on one field under different perturbations, so the field
    alone does not identify it. If several apply to the same cell, the strictest wins."""
    declared = [i.threshold for i in contract.invariants
                if i.relation is Relation.jaccard_at_least and i.field == field
                and i.threshold is not None and perturbation in {p.value for p in i.under}]
    return max(declared) if declared else None


def _malformed_rate(samples: list[Sample]) -> float:
    return sum(1 for s in samples if s.parsed is None) / len(samples)


def _monotonic_cell(contract: Contract, entry: PlanEntry, ladder: list[str],
                    sut: SUT, t: int, seed: int) -> CellResult:
    rungs = collect_ladder(entry, ladder, sut, t, seed)
    flat = [s for rung in rungs for s in rung]
    violation = {
        inv.field: monotonic_violation_rate(rungs, inv.field, inv.order or [])
        for inv in contract.invariants
        if inv.relation is Relation.monotonic and inv.field in entry.invariant_fields
    }
    return CellResult(
        metrics=CellMetrics(
            probe_id=entry.probe_id, perturbation=entry.perturbation.value, n=len(flat),
            malformed_rate=_malformed_rate(flat), flip_rate=violation,
            jaccard_mean={}, semantic_variance=0.0),
        modes=None,
    )


def execute_plan(
    contract: Contract,
    entries: list[PlanEntry],
    sut: SUT,
    *,
    t: int,
    seed: int,
    embedder: Embedder,
    paraphrases: dict[str, list[str]] | None = None,
) -> RunOutcome:
    """Run every executable cell at time step t and decide the gate.

    paraphrases: probe id -> accepted, back-checked variants (engine.metamorphic).
    """
    probes = {p.id: p for p in contract.probes}
    wording = contract.allowed_variation[0].field if contract.allowed_variation else ""
    references: dict[str, list[Sample]] = {}

    def text_of(probe_id: str) -> str:
        """Simulators and user systems take text. An object input belongs to a golden-set
        contract, which is scored by app.jev_runner, not sampled here."""
        value = probes[probe_id].input
        if not isinstance(value, str):
            raise ValueError(f"probe '{probe_id}' has an object input; this executor samples text probes")
        return value

    def reference_for(entry: PlanEntry) -> list[Sample]:
        """The unperturbed seed's samples: what a perturbed cell is compared against."""
        if entry.probe_id not in references:
            seed_entry = entry.model_copy(update={"perturbation": Perturbation.repeat_run})
            references[entry.probe_id] = collect(
                seed_entry, text_of(entry.probe_id), sut, t=t, seed=seed)
        return references[entry.probe_id]

    cells: list[CellResult] = []
    skipped: list[dict] = []
    for entry in entries:
        probe = probes[entry.probe_id]
        if entry.perturbation is Perturbation.monotonic:
            cells.append(_monotonic_cell(contract, entry, probe.ladder or [], sut, t, seed))
            continue
        variants = (paraphrases or {}).get(entry.probe_id)
        if entry.perturbation is Perturbation.paraphrase and not variants:
            skipped.append({"probe": entry.probe_id, "perturbation": entry.perturbation.value,
                            "reason": "no accepted paraphrase variants generated yet"})
            continue
        samples = collect(entry, text_of(entry.probe_id), sut, t=t, seed=seed, paraphrases=variants)
        equal = _fields(contract, entry, Relation.equal)
        jaccard = _fields(contract, entry, Relation.jaccard_at_least)
        reference = None if entry.perturbation is Perturbation.repeat_run else reference_for(entry)
        cells.append(CellResult(
            metrics=canonicalize(samples, equal, jaccard, wording, embedder, reference=reference),
            modes=cluster_modes(samples, equal + jaccard),
        ))

    if not cells:
        raise NothingMeasured(
            "contract has no executable plan cells (its only cells are paraphrase cells "
            "and no variants have been generated)")
    return _decide(contract, tuple(cells), tuple(skipped))


def _reasons(contract: Contract, worst_flip: float, worst_malformed: float,
             jaccard_failures: list[dict], second_modes: list[dict]) -> list[str]:
    """One line per tripped rule. Empty means the gate passes."""
    gate = contract.gate
    reasons: list[str] = []
    if worst_flip > gate.max_decision_flip_rate:
        reasons.append(f"flip rate {worst_flip:.1%} exceeds the {gate.max_decision_flip_rate:.1%} tolerance")
    if worst_malformed > gate.max_malformed_rate:
        reasons.append(f"malformed rate {worst_malformed:.1%} exceeds the {gate.max_malformed_rate:.1%} tolerance")
    if jaccard_failures:
        reasons.append(f"{len(jaccard_failures)} cell(s) under a declared Jaccard threshold")
    limit = gate.max_second_mode_share
    if limit is not None:
        over = [s for s in second_modes if s["share"] > limit]
        if over:
            reasons.append(f"{len(over)} cell(s) with a second mode above {limit:.1%}")
    return reasons


def _decide(contract: Contract, cells: tuple[CellResult, ...],
            skipped: tuple[dict, ...]) -> RunOutcome:
    worst_flip, worst_malformed = 0.0, 0.0
    worst_cell: dict | None = None
    jaccard_failures: list[dict] = []
    second_modes: list[dict] = []
    for cell in cells:
        m = cell.metrics
        for field, rate in m.flip_rate.items():
            if rate > worst_flip:
                worst_flip = rate
                worst_cell = {"probe": m.probe_id, "perturbation": m.perturbation, "field": field}
        worst_malformed = max(worst_malformed, m.malformed_rate)
        for field, observed in m.jaccard_mean.items():
            threshold = jaccard_threshold(contract, field, m.perturbation)
            if threshold is not None and observed < threshold:
                jaccard_failures.append({
                    "probe": m.probe_id, "perturbation": m.perturbation, "field": field,
                    "jaccard_mean": observed, "threshold": threshold})
        if cell.modes is not None and len(cell.modes.modes) > 1:
            second_modes.append({
                "probe": m.probe_id, "perturbation": m.perturbation,
                "share": cell.modes.second_mode_share,
                "detected": cell.modes.second_mode_detected})

    reasons = _reasons(contract, worst_flip, worst_malformed, jaccard_failures, second_modes)

    return RunOutcome(
        cells=cells, skipped=skipped,
        decision="block" if reasons else "pass", reasons=tuple(reasons),
        worst_flip_rate=worst_flip, worst_cell=worst_cell,
        worst_malformed_rate=worst_malformed,
        jaccard_failures=tuple(jaccard_failures), second_modes=tuple(second_modes),
    )
