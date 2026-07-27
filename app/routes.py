"""Business endpoints: the contract -> run -> report loop, persisted.

POST /api/v1/contracts   register a contract (YAML) and its compiled plan
POST /api/v1/runs        execute the plan's repeat_run cells against a named SUT, store metrics
GET  /api/v1/reports/{contract}   metrics history, chart points once warmed, gate decision

Real processing, zero external keys: SUTs are in-process and the default embedder is the
deterministic one; the real embedder is an explicit request choice. When SMOKE_TEST_TOKEN is
set, mutating endpoints require it as a bearer token.
"""
from __future__ import annotations

import sqlalchemy as sa
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError

from . import db
from .config import settings
from .engine.canonicalize import canonicalize
from .engine.charts import IndividualsChart
from .engine.contracts import (
    Perturbation, Relation, compile_plan, load_contract, PlanEntry,
)
from .engine.embedding import HashingEmbedder, OpenRouterEmbedder
from .engine.sampler import collect
from .engine.suts import DEMO_SUTS

router = APIRouter(prefix="/api/v1")

BASELINE_MIN = 8


def _auth(authorization: str | None) -> None:
    # Empty token = auth off, permitted in development ONLY: app.main.require_production_auth
    # refuses to start the app outside development with an empty token.
    token = settings.smoke_test_token
    if token and authorization != f"Bearer {token}":
        raise HTTPException(status_code=401, detail="missing or invalid bearer token")


class ContractIn(BaseModel):
    yaml: str


class RunIn(BaseModel):
    contract: str
    sut: str = "stable"
    t: int = Field(default=0, ge=0)
    seed: int = 7
    embedder: str = Field(default="hashing", pattern="^(hashing|openrouter)$")


def _embedder(name: str):
    if name == "openrouter":
        return OpenRouterEmbedder(
            api_key=settings.openrouter_api_key,
            model=settings.embedding_model,
            base_url=settings.openrouter_base_url,
        )
    return HashingEmbedder()


@router.post("/contracts", status_code=201)
def register_contract(body: ContractIn, authorization: str | None = Header(default=None)):
    _auth(authorization)
    try:
        contract = load_contract(body.yaml)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    plan = compile_plan(contract)
    try:
        with db.get_session() as s, s.begin():
            existing = s.execute(
                sa.select(db.contracts.c.id).where(db.contracts.c.name == contract.contract)
            ).first()
            if existing:
                raise HTTPException(status_code=409, detail="contract already registered")
            cid = s.execute(
                db.contracts.insert().values(
                    name=contract.contract, subject=contract.subject,
                    yaml=body.yaml, plan_id=plan.plan_id,
                )
            ).inserted_primary_key[0]
            for p in contract.probes:
                s.execute(db.probes.insert().values(
                    contract_id=cid, probe_key=p.id, input=p.input))
            s.execute(db.experiment_plans.insert().values(
                contract_id=cid, plan_id=plan.plan_id,
                entries=[e.model_dump(mode="json") for e in plan.entries]))
    except IntegrityError:
        # Concurrent registration race: both requests pass the pre-check, the unique
        # index catches the loser. Same documented outcome as the pre-check: 409.
        raise HTTPException(status_code=409, detail="contract already registered")
    return {"contract": contract.contract, "plan_id": plan.plan_id,
            "entries": len(plan.entries)}


@router.post("/runs", status_code=201)
def execute_run(body: RunIn, authorization: str | None = Header(default=None)):
    _auth(authorization)
    sut = DEMO_SUTS.get(body.sut)
    if sut is None:
        raise HTTPException(status_code=422, detail=f"unknown sut '{body.sut}'")
    with db.get_session() as s, s.begin():
        row = s.execute(
            sa.select(db.contracts).where(db.contracts.c.name == body.contract)
        ).first()
        if row is None:
            raise HTTPException(status_code=404, detail="contract not registered")
        contract = load_contract(row.yaml)
        plan_row = s.execute(
            sa.select(db.experiment_plans).where(db.experiment_plans.c.contract_id == row.id)
        ).first()
        probe_inputs = {p.id: p.input for p in contract.probes}

        equal_fields = [i.field for i in contract.invariants if i.relation is Relation.equal]
        jaccard_fields = [i.field for i in contract.invariants
                          if i.relation is Relation.jaccard_at_least]
        wording = contract.allowed_variation[0].field if contract.allowed_variation else ""
        embedder = _embedder(body.embedder)

        jaccard_thresholds = {i.field: i.threshold for i in contract.invariants
                              if i.relation is Relation.jaccard_at_least}

        run_id = s.execute(db.runs.insert().values(
            plan_fk=plan_row.id, t=body.t, seed=body.seed, sut=body.sut,
            embedder=embedder.name)).inserted_primary_key[0]

        worst_flip = 0.0
        worst_malformed = 0.0
        jaccard_failures: list[dict] = []
        stored = 0
        for e_json in plan_row.entries:
            entry = PlanEntry.model_validate(e_json)
            if entry.perturbation is not Perturbation.repeat_run:
                continue        # paraphrase cells need generated variants (M8); report notes it
            samples = collect(entry, probe_inputs[entry.probe_id], sut,
                              t=body.t, seed=body.seed)
            m = canonicalize(samples, equal_fields, jaccard_fields, wording, embedder)
            s.execute(db.consistency_metrics.insert().values(
                run_id=run_id, probe_key=m.probe_id, perturbation=m.perturbation,
                n=m.n, malformed_rate=m.malformed_rate, flip_rate=m.flip_rate,
                jaccard_mean=m.jaccard_mean, semantic_variance=m.semantic_variance))
            stored += 1
            worst_flip = max(worst_flip, *m.flip_rate.values()) if m.flip_rate else worst_flip
            worst_malformed = max(worst_malformed, m.malformed_rate)
            for f, min_j in jaccard_thresholds.items():
                observed = m.jaccard_mean.get(f)
                if observed is not None and observed < min_j:
                    jaccard_failures.append({"probe": m.probe_id, "field": f,
                                             "jaccard_mean": observed, "threshold": min_j})

        if stored == 0:
            # A gate decision with zero measurements would be a recorded pass over nothing
            # (Standard 3: a plan cell is never silently skipped). Fail loud; the rollback
            # discards the empty run.
            raise HTTPException(
                status_code=422,
                detail="contract has no executable plan cells (paraphrase-only contracts "
                       "need generated variants; lands in M8)")

        threshold = contract.gate.max_decision_flip_rate
        mal_threshold = contract.gate.max_malformed_rate
        decision = "pass"
        if worst_flip > threshold or worst_malformed > mal_threshold or jaccard_failures:
            decision = "block"
        s.execute(db.gate_decisions.insert().values(
            contract_id=row.id, run_id=run_id, decision=decision,
            worst_flip_rate=worst_flip, threshold=threshold,
            evidence={"cells": stored, "t": body.t, "seed": body.seed, "sut": body.sut,
                      "worst_malformed_rate": worst_malformed,
                      "max_malformed_rate": mal_threshold,
                      "jaccard_failures": jaccard_failures}))
    return {"run_id": run_id, "cells": stored, "gate": decision,
            "worst_flip_rate": worst_flip, "threshold": threshold,
            "worst_malformed_rate": worst_malformed,
            "jaccard_failures": jaccard_failures}


@router.get("/reports/{contract_name}")
def report(contract_name: str, authorization: str | None = Header(default=None)):
    _auth(authorization)
    with db.get_session() as s:
        row = s.execute(
            sa.select(db.contracts).where(db.contracts.c.name == contract_name)
        ).first()
        if row is None:
            raise HTTPException(status_code=404, detail="contract not registered")
        metrics = s.execute(
            sa.select(db.consistency_metrics, db.runs.c.t)
            .select_from(db.consistency_metrics.join(
                db.runs, db.consistency_metrics.c.run_id == db.runs.c.id))
            .join(db.experiment_plans, db.runs.c.plan_fk == db.experiment_plans.c.id)
            .where(db.experiment_plans.c.contract_id == row.id)
            .order_by(db.runs.c.t)
        ).mappings().all()
        gates = s.execute(
            sa.select(db.gate_decisions).where(db.gate_decisions.c.contract_id == row.id)
            .order_by(db.gate_decisions.c.id)
        ).mappings().all()

        # Chart from accumulated worst-flip series once the baseline window is warm.
        series = [max(g["worst_flip_rate"], 0.0) for g in gates]
        chart_points = []
        if len(series) >= BASELINE_MIN + 1:
            chart = IndividualsChart(series[:BASELINE_MIN])
            for i, v in enumerate(series[BASELINE_MIN:], start=BASELINE_MIN):
                p = chart.add(i, v)
                chart_points.append({"t": p.t, "value": p.value, "center": p.center,
                                     "ucl": p.ucl, "lcl": p.lcl, "alarm": p.alarm,
                                     "rule": p.rule})

    return {
        "contract": contract_name,
        "plan_id": row.plan_id,
        "runs": len(gates),
        "latest_gate": dict(gates[-1]) if gates else None,
        "metrics": [dict(m) for m in metrics],
        "chart": {
            "warm": len(series) >= BASELINE_MIN + 1,
            "baseline_needed": BASELINE_MIN,
            "points": chart_points,
        },
        "notes": ["paraphrase cells execute once variants are generated (engine.metamorphic)"],
    }
