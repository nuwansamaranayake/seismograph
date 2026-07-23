"""Behavioral contracts as code: YAML -> validated Contract -> deterministic ExperimentPlan.

The contract declares what must not vary, what may vary, and how much variation is acceptable.
Compilation is pure: the same contract text always yields the same plan (same plan_id), so a
plan is reproducible from the contract alone and can gate CI.
"""
from __future__ import annotations

import hashlib
import json
from enum import Enum

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator


class Perturbation(str, Enum):
    repeat_run = "repeat_run"
    paraphrase = "paraphrase"
    irrelevant_context = "irrelevant_context"
    reordering = "reordering"


# Perturbations whose variant generators exist in Phase 1. Declaring others in a contract is
# valid (the language is the product's spine); *executing* them raises loudly, never skips.
EXECUTABLE_PERTURBATIONS = {Perturbation.repeat_run, Perturbation.paraphrase}


class Relation(str, Enum):
    equal = "equal"
    jaccard_at_least = "jaccard_at_least"


class Invariant(BaseModel):
    field: str
    under: list[Perturbation] = Field(min_length=1)
    relation: Relation
    threshold: float | None = None

    @model_validator(mode="after")
    def _threshold_rules(self) -> "Invariant":
        if self.relation is Relation.jaccard_at_least and self.threshold is None:
            raise ValueError("relation jaccard_at_least requires a threshold")
        if self.relation is Relation.equal and self.threshold is not None:
            raise ValueError("relation equal takes no threshold")
        if self.threshold is not None and not 0.0 < self.threshold <= 1.0:
            raise ValueError("threshold must be in (0, 1]")
        return self


class AllowedVariation(BaseModel):
    field: str
    rule: str


class RunPolicy(BaseModel):
    samples: int = Field(ge=2, le=1000)
    configs: int = Field(ge=1, le=10)
    confidence: float = Field(gt=0.5, lt=1.0)


class GatePolicy(BaseModel):
    max_decision_flip_rate: float = Field(ge=0.0, le=1.0)


class ProbeSeed(BaseModel):
    id: str
    input: str

    @field_validator("id")
    @classmethod
    def _id_nonempty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("probe id must be non-empty")
        return v


class Contract(BaseModel):
    contract: str
    subject: str
    invariants: list[Invariant] = Field(min_length=1)
    allowed_variation: list[AllowedVariation] = Field(default_factory=list)
    run_policy: RunPolicy
    gate: GatePolicy
    probes: list[ProbeSeed] = Field(min_length=1)

    @model_validator(mode="after")
    def _unique_probe_ids(self) -> "Contract":
        ids = [p.id for p in self.probes]
        if len(ids) != len(set(ids)):
            raise ValueError("probe ids must be unique")
        return self


class PlanEntry(BaseModel):
    """One cell of the experiment grid: a probe run under one perturbation, N x M times."""
    probe_id: str
    perturbation: Perturbation
    invariant_fields: list[str]
    samples: int
    configs: int


class ExperimentPlan(BaseModel):
    plan_id: str
    contract_name: str
    subject: str
    entries: list[PlanEntry]


def load_contract(text: str) -> Contract:
    data = yaml.safe_load(text)
    if not isinstance(data, dict):
        raise ValueError("contract YAML must be a mapping")
    return Contract.model_validate(data)


def compile_plan(contract: Contract) -> ExperimentPlan:
    """Deterministic: entries are emitted in sorted order and plan_id is a content hash."""
    grid: dict[tuple[str, Perturbation], set[str]] = {}
    for probe in contract.probes:
        for inv in contract.invariants:
            for pert in inv.under:
                grid.setdefault((probe.id, pert), set()).add(inv.field)
    entries = [
        PlanEntry(
            probe_id=probe_id,
            perturbation=pert,
            invariant_fields=sorted(fields),
            samples=contract.run_policy.samples,
            configs=contract.run_policy.configs,
        )
        for (probe_id, pert), fields in sorted(
            grid.items(), key=lambda kv: (kv[0][0], kv[0][1].value)
        )
    ]
    digest = hashlib.sha256(
        json.dumps(
            [contract.model_dump(mode="json"), [e.model_dump(mode="json") for e in entries]],
            sort_keys=True,
        ).encode()
    ).hexdigest()[:16]
    return ExperimentPlan(
        plan_id=digest,
        contract_name=contract.contract,
        subject=contract.subject,
        entries=entries,
    )
