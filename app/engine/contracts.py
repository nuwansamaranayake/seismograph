"""Behavioral contracts as code: YAML -> validated Contract -> deterministic ExperimentPlan.

The contract declares what must not vary, what may vary, and how much variation is acceptable.
Compilation is pure: the same contract text always yields the same plan (same plan_id), so a
plan is reproducible from the contract alone and can gate CI.
"""
from __future__ import annotations

import hashlib
import json
from enum import Enum
from pathlib import Path

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator

from .perturb import DETERMINISTIC_PERTURBATIONS, variants_for


class Perturbation(str, Enum):
    repeat_run = "repeat_run"
    paraphrase = "paraphrase"
    irrelevant_context = "irrelevant_context"
    reordering = "reordering"
    format = "format"  # type: ignore[assignment]  # a str enum member named like str.format
    # A ladder of inputs ordered along one quantity (days since purchase, order value).
    # The invariant is on the direction the output may move, not on equality.
    monotonic = "monotonic"


# Every perturbation has a generator. Paraphrase is the only one that needs a model to
# propose variants (engine.metamorphic); the rest are deterministic (engine.perturb,
# and the probe's own ladder for monotonic). Executing a cell with no variants available
# still raises loudly, never skips.
EXECUTABLE_PERTURBATIONS = set(Perturbation)


class Relation(str, Enum):
    equal = "equal"
    jaccard_at_least = "jaccard_at_least"
    monotonic = "monotonic"


class Invariant(BaseModel):
    field: str
    under: list[Perturbation] = Field(min_length=1)
    relation: Relation
    threshold: float | None = None
    # relation monotonic: the field's values from the first rung's side to the last
    # rung's side, e.g. [eligible, ineligible] as days-since-purchase grows.
    order: list[str] | None = None

    @model_validator(mode="after")
    def _threshold_rules(self) -> Invariant:
        if self.relation is Relation.jaccard_at_least and self.threshold is None:
            raise ValueError("relation jaccard_at_least requires a threshold")
        if self.relation is not Relation.jaccard_at_least and self.threshold is not None:
            raise ValueError(f"relation {self.relation.value} takes no threshold")
        if self.threshold is not None and not 0.0 < self.threshold <= 1.0:
            raise ValueError("threshold must be in (0, 1]")
        is_monotonic = self.relation is Relation.monotonic
        if is_monotonic != (self.under == [Perturbation.monotonic]):
            raise ValueError("relation monotonic pairs with `under: [monotonic]` and nothing else")
        if is_monotonic and (not self.order or len(set(self.order)) < 2):
            raise ValueError("relation monotonic requires `order` with at least two distinct values")
        if not is_monotonic and self.order is not None:
            raise ValueError(f"relation {self.relation.value} takes no order")
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
    # Malformed output is a defect class of its own (the FlakySUT class): it must gate the
    # run directly, not vanish from the flip rate because unparsed samples carry no fields.
    # Default 0.0: any malformed sample blocks unless the contract explicitly tolerates it.
    max_malformed_rate: float = Field(default=0.0, ge=0.0, le=1.0)
    # Optional: block when any cell shows a second outcome mode above this share
    # (engine.modes). Unset means modes are reported and do not gate.
    max_second_mode_share: float | None = Field(default=None, ge=0.0, le=1.0)
    # Gates for golden-set contracts against a typed-judgment SUT (app/jev_runner.py).
    # Optional so existing contracts are unchanged; a golden contract declares the ones
    # its `golden.kind` scores.
    confidence_cutoff: float | None = Field(default=None, ge=0.0, le=1.0)
    min_recall: float | None = Field(default=None, ge=0.0, le=1.0)
    max_false_positive_rate: float | None = Field(default=None, ge=0.0, le=1.0)
    min_top1_accuracy: float | None = Field(default=None, ge=0.0, le=1.0)


class ProbeSeed(BaseModel):
    id: str
    # A string for text probes; a JSON object when the SUT takes structured state
    # (docs.typesafe.ai/concepts/state: named fields for multi-part context).
    input: str | dict
    # Ground truth for golden-set probes (label, violation_type, choice ...). Absent for
    # probes that are judged by invariants alone.
    expected: dict | None = None
    # Inputs ordered along one quantity, for monotonic invariants. `input` stays the
    # probe's seed for every other perturbation.
    ladder: list[str] | None = None

    @field_validator("id")
    @classmethod
    def _id_nonempty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("probe id must be non-empty")
        return v

    @field_validator("ladder")
    @classmethod
    def _ladder_has_steps(cls, v: list[str] | None) -> list[str] | None:
        if v is not None and len(v) < 2:
            raise ValueError("a ladder needs at least two rungs")
        return v


class SutSpec(BaseModel):
    """A system under test named in the contract itself (as opposed to a demo SUT picked
    on the command line). `jev` is the TypeSafe System One adapter in app/jev.py."""

    adapter: str
    model: str
    timeout_seconds: float = Field(default=30.0, gt=0.0)


class GoldenSpec(BaseModel):
    """Where the probes with ground truth live and how they are scored.

    kind:
      noul_flag    each probe row carries `label` (== positive_label or not) and an optional
                   `violation_type`; the run flags a probe when any noul >= confidence_cutoff.
      choice_top1  each probe row carries `expected`, the option the choice must pick.
    """

    path: str
    kind: str
    positive_label: str = "violation"
    type_to_question: dict[str, str] = Field(default_factory=dict)
    # noul_flag: flag on this one noul question only. None means any noul question.
    flag_question: str | None = None
    # noul_flag: the golden row field holding the text or object sent as state.
    state_field: str = "text"
    # Refuse to run (and report the count) when the golden set is smaller than this.
    min_rows: int = Field(default=1, ge=1)
    metadata: dict = Field(default_factory=dict)

    @field_validator("kind")
    @classmethod
    def _known_kind(cls, v: str) -> str:
        if v not in {"noul_flag", "choice_top1"}:
            raise ValueError(f"unknown golden kind {v!r}")
        return v


class Contract(BaseModel):
    contract: str
    subject: str
    invariants: list[Invariant] = Field(min_length=1)
    allowed_variation: list[AllowedVariation] = Field(default_factory=list)
    run_policy: RunPolicy
    gate: GatePolicy
    probes: list[ProbeSeed] = Field(default_factory=list)
    # Golden-set contracts (added 2026-09-21 for the Jev SUT): the SUT, its typed
    # questions, and the golden file whose rows become the probes at load time.
    sut: SutSpec | None = None
    questions: dict[str, dict] | None = None
    golden: GoldenSpec | None = None

    @model_validator(mode="after")
    def _unique_probe_ids(self) -> Contract:
        ids = [p.id for p in self.probes]
        if len(ids) != len(set(ids)):
            raise ValueError("probe ids must be unique")
        if not self.probes and self.golden is None:
            raise ValueError("contract needs at least one probe or a golden set")
        if self.sut is not None and not self.questions:
            raise ValueError("a contract with a sut must declare questions")
        return self

    @model_validator(mode="after")
    def _perturbations_are_executable(self) -> Contract:
        """A cell that cannot run is refused at registration, with the probe named. The
        alternative is a plan entry that raises mid-run, or worse, one that is skipped."""
        declared = {p for inv in self.invariants for p in inv.under}
        text_only = sorted(p.value for p in declared if p in DETERMINISTIC_PERTURBATIONS)
        for probe in self.probes:
            if not text_only:
                continue
            if not isinstance(probe.input, str):
                raise ValueError(
                    f"probe '{probe.id}': {text_only} need a text input, got an object")
            for name in text_only:
                # Ask the generator itself. Whatever it cannot produce a variant for (one
                # sentence, or sentences that all read the same) is refused here by name,
                # not discovered as a crash in the middle of a run.
                try:
                    variants_for(name, probe.input, 1)
                except ValueError as e:
                    raise ValueError(f"probe '{probe.id}': {e}") from e
        if Perturbation.monotonic in declared and not any(p.ladder for p in self.probes):
            raise ValueError("a monotonic invariant needs at least one probe with a ladder")
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


def _golden_rows_to_probes(rows: list[dict], kind: str, where: str, state_field: str = "text") -> list[dict]:
    probes = []
    for i, row in enumerate(rows):
        if "id" not in row:
            raise ValueError(f"{where}: row {i} has no id")
        if kind == "noul_flag":
            if "label" not in row or state_field not in row:
                raise ValueError(f"{where}: row {row['id']} needs label and {state_field}")
            expected = {k: row[k] for k in ("label", "violation_type", "engine_level", "engine_score") if k in row}
            probes.append({"id": row["id"], "input": row[state_field], "expected": expected})
        elif kind != "choice_top1":
            # Named here, before any row is read as a kind it is not: the model validator
            # that also rejects this runs later, after the rows would have been misreported.
            raise ValueError(f"{where}: unknown golden kind {kind!r}")
        else:
            if "expected" not in row or "prompt" not in row:
                raise ValueError(f"{where}: row {row['id']} needs prompt and expected")
            probes.append({"id": row["id"], "input": row["prompt"], "expected": {"choice": row["expected"]}})
    return probes


def load_contract(text: str, base_dir: Path | None = None) -> Contract:
    """Parse contract YAML. A golden-set contract needs `base_dir` (the contract file's
    directory) so its golden rows become probes and any `criteria_from` file is inlined;
    a missing golden file raises rather than yielding a contract with zero probes."""
    data = yaml.safe_load(text)
    if not isinstance(data, dict):
        raise ValueError("contract YAML must be a mapping")
    golden = data.get("golden")
    if isinstance(golden, dict):
        if base_dir is None:
            raise ValueError("golden-set contract needs base_dir to resolve golden.path")
        path = Path(base_dir) / golden["path"]
        if not path.exists():
            raise ValueError(f"golden set missing: {path}")
        rows = [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
        if not rows:
            raise ValueError(
                f"golden set has 0 labeled rows; contract requires at least "
                f"{int(golden.get('min_rows', 1))}. Not running. ({path})"
            )
        data["probes"] = list(data.get("probes") or []) + _golden_rows_to_probes(
            rows, golden.get("kind", ""), str(path), golden.get("state_field", "text"))
        for qid, q in (data.get("questions") or {}).items():
            src = q.pop("criteria_from", None)
            if src:
                opts_path = Path(base_dir) / src
                if not opts_path.exists():
                    raise ValueError(f"question {qid}: criteria_from file missing: {opts_path}")
                q["criteria"] = json.loads(opts_path.read_text(encoding="utf-8"))
    return Contract.model_validate(data)


def compile_plan(contract: Contract) -> ExperimentPlan:
    """Deterministic: entries are emitted in sorted order and plan_id is a content hash."""
    grid: dict[tuple[str, Perturbation], set[str]] = {}
    for probe in contract.probes:
        for inv in contract.invariants:
            for pert in inv.under:
                if pert is Perturbation.monotonic and not probe.ladder:
                    continue    # a ladder is a property of the probe; only laddered probes get the cell
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
