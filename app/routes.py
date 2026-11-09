"""Business endpoints: the contract -> run -> report loop, persisted.

POST /api/v1/contracts   register a contract (YAML) and its compiled plan
POST /api/v1/runs        execute every executable plan cell against a named simulator, store
                         metrics, outcome modes and the gate decision
GET  /api/v1/reports/{contract}   run series, control charts once warmed, mode topology,
                                  invariant matrix, latest gate decision

Real processing, zero external keys: systems under test are in-process simulators and the
default embedder is the deterministic one; the real embedder is an explicit request choice.
When SMOKE_TEST_TOKEN is set, every endpoint here requires it as a bearer token.

The gate is decided in engine.execute, not here: this module stores and serves.
"""
from __future__ import annotations

import sqlalchemy as sa
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError

from . import db
from .config import settings
from .engine import modes as mode_engine
from .engine.charts import IndividualsChart, PChart
from .engine.contracts import Contract, PlanEntry, compile_plan, load_contract
from .engine.embedding import HashingEmbedder, OpenRouterEmbedder
from .engine.execute import NothingMeasured, execute_plan, jaccard_threshold
from .engine.suts import DEMO_SUTS

router = APIRouter(prefix="/api/v1")

BASELINE_MIN = 8
MODE_WINDOW = 12        # runs pooled when looking for a small, persistent second mode


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


def contract_row(session, name: str):
    row = session.execute(sa.select(db.contracts).where(db.contracts.c.name == name)).first()
    if row is None:
        raise HTTPException(status_code=404, detail="contract not registered")
    return row


@router.post("/contracts", status_code=201)
def register_contract(body: ContractIn, authorization: str | None = Header(default=None)):
    _auth(authorization)
    try:
        contract = load_contract(body.yaml)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
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
        raise HTTPException(status_code=409, detail="contract already registered") from None
    return {"contract": contract.contract, "plan_id": plan.plan_id,
            "entries": len(plan.entries)}


def _accepted_paraphrases(session, contract_id: int) -> dict[str, list[str]]:
    rows = session.execute(
        sa.select(db.probes.c.probe_key, db.probe_variants.c.variant_input)
        .select_from(db.probe_variants.join(
            db.probes, db.probe_variants.c.probe_id == db.probes.c.id))
        .where(db.probes.c.contract_id == contract_id,
               db.probe_variants.c.perturbation == "paraphrase",
               db.probe_variants.c.accepted.is_(True))
        .order_by(db.probe_variants.c.id)
    ).all()
    out: dict[str, list[str]] = {}
    for probe_key, variant in rows:
        out.setdefault(probe_key, []).append(variant)
    return out


@router.post("/runs", status_code=201)
def execute_run(body: RunIn, authorization: str | None = Header(default=None)):
    _auth(authorization)
    sut = DEMO_SUTS.get(body.sut)
    if sut is None:
        raise HTTPException(status_code=422, detail=f"unknown sut '{body.sut}'")
    with db.get_session() as s, s.begin():
        row = contract_row(s, body.contract)
        contract = load_contract(row.yaml)
        plan_row = s.execute(
            sa.select(db.experiment_plans).where(db.experiment_plans.c.contract_id == row.id)
        ).first()
        try:
            embedder = _embedder(body.embedder)
        except RuntimeError as e:
            # The real embedder refuses to run without a key and a pinned model. That is
            # a capability this instance lacks, not a server fault: 503, with the reason.
            raise HTTPException(status_code=503, detail=str(e)) from e
        try:
            outcome = execute_plan(
                contract, [PlanEntry.model_validate(e) for e in plan_row.entries], sut,
                t=body.t, seed=body.seed, embedder=embedder,
                paraphrases=_accepted_paraphrases(s, row.id))
        except NothingMeasured as e:
            # A gate decision with zero measurements would be a recorded pass over nothing
            # (Standard 3: a plan cell is never silently skipped). Fail loud; nothing is stored.
            raise HTTPException(status_code=422, detail=str(e)) from e

        run_id = s.execute(db.runs.insert().values(
            plan_fk=plan_row.id, t=body.t, seed=body.seed, sut=body.sut,
            embedder=embedder.name)).inserted_primary_key[0]
        for cell in outcome.cells:
            m = cell.metrics
            s.execute(db.consistency_metrics.insert().values(
                run_id=run_id, probe_key=m.probe_id, perturbation=m.perturbation,
                n=m.n, malformed_rate=m.malformed_rate, flip_rate=m.flip_rate,
                jaccard_mean=m.jaccard_mean, semantic_variance=m.semantic_variance))
            if cell.modes is not None:
                s.execute(db.outcome_modes.insert().values(
                    run_id=run_id, probe_key=m.probe_id, perturbation=m.perturbation,
                    n=cell.modes.n, modes=cell.modes.to_json()["modes"],
                    second_mode_share=cell.modes.second_mode_share,
                    second_mode_detected=cell.modes.second_mode_detected))

        threshold = contract.gate.max_decision_flip_rate
        s.execute(db.gate_decisions.insert().values(
            contract_id=row.id, run_id=run_id, decision=outcome.decision,
            worst_flip_rate=outcome.worst_flip_rate, threshold=threshold,
            evidence=outcome.evidence() | {
                "t": body.t, "seed": body.seed, "sut": body.sut,
                "max_malformed_rate": contract.gate.max_malformed_rate}))
    return {"run_id": run_id, "cells": len(outcome.cells), "gate": outcome.decision,
            "reasons": list(outcome.reasons),
            "worst_flip_rate": outcome.worst_flip_rate, "threshold": threshold,
            "worst_cell": outcome.worst_cell,
            "worst_malformed_rate": outcome.worst_malformed_rate,
            "jaccard_failures": list(outcome.jaccard_failures),
            "second_modes": list(outcome.second_modes),
            "skipped": list(outcome.skipped)}


def _points(chart, series: list[float]) -> list[dict]:
    out = []
    for i, v in enumerate(series[BASELINE_MIN:], start=BASELINE_MIN):
        p = chart.add(i, v)
        out.append({"t": p.t, "value": p.value, "center": p.center, "ucl": p.ucl,
                    "lcl": p.lcl, "alarm": p.alarm, "rule": p.rule})
    return out


def control_chart(series: list[float], p_chart_n: int | None = None) -> dict:
    """Chart a series once BASELINE_MIN + 1 points exist. The first BASELINE_MIN points
    set the limits and are never judged against them; limits are frozen after that.
    p_chart_n switches to a proportion chart with that sample size per point."""
    warm = len(series) > BASELINE_MIN
    points: list[dict] = []
    if warm:
        baseline = series[:BASELINE_MIN]
        chart = PChart(baseline, p_chart_n) if p_chart_n else IndividualsChart(baseline)
        points = _points(chart, series)
    return {"warm": warm, "baseline_needed": BASELINE_MIN,
            "runs_until_warm": max(0, BASELINE_MIN + 1 - len(series)), "points": points}


def _mode_topology(mode_rows: list, run_order: dict[int, int], run_t: dict[int, int]) -> list[dict]:
    """Per cell: the mode shares of each run, and the modes pooled over the last
    MODE_WINDOW runs. Pooling is what makes a small persistent mode provable."""
    cells: dict[tuple[str, str], list] = {}
    for r in sorted(mode_rows, key=lambda r: run_order[r["run_id"]]):
        cells.setdefault((r["probe_key"], r["perturbation"]), []).append(r)
    out = []
    for (probe, perturbation), rows in sorted(cells.items()):
        reports = [mode_engine.from_json({
            "n": r["n"], "modes": r["modes"],
            "second_mode_share": r["second_mode_share"],
            "second_mode_low": 0.0,     # not stored per run; the pooled bound is the claim
            "second_mode_detected": r["second_mode_detected"]}) for r in rows]
        window = reports[-MODE_WINDOW:]
        out.append({
            "probe": probe, "perturbation": perturbation,
            "window": len(window),
            "pooled": mode_engine.pool(window).to_json(),
            "by_run": [{"run_id": r["run_id"], "t": run_t[r["run_id"]], "n": rep.n,
                        "shares": {m.key: m.share for m in rep.modes}}
                       for r, rep in zip(rows, reports, strict=True)],
        })
    return out


def invariant_matrix(contract: Contract, metric_rows: list,
                     mode_rows: list | None = None) -> list[dict]:
    """One row per measured cell of a run, with the verdict the gate reached on it. Every
    rule the gate applies is applied here, so a blocked run always shows the cell that
    blocked it."""
    gate = contract.gate
    second_mode = {(m["probe_key"], m["perturbation"]): m["second_mode_share"]
                   for m in mode_rows or []}
    out = []
    for m in metric_rows:
        flip = max(m["flip_rate"].values(), default=0.0)
        under = [f for f, v in m["jaccard_mean"].items()
                 if (jaccard_threshold(contract, f, m["perturbation"]) or 0.0) > v]
        share = second_mode.get((m["probe_key"], m["perturbation"]), 0.0)
        over_mode = gate.max_second_mode_share is not None and share > gate.max_second_mode_share
        violated = (flip > gate.max_decision_flip_rate
                    or m["malformed_rate"] > gate.max_malformed_rate or bool(under) or over_mode)
        out.append({"probe": m["probe_key"], "perturbation": m["perturbation"], "n": m["n"],
                    "flip_rate": flip, "malformed_rate": m["malformed_rate"],
                    "jaccard_mean": m["jaccard_mean"],
                    "semantic_variance": m["semantic_variance"],
                    "second_mode_share": share, "violated": violated})
    return out


@router.get("/reports/{contract_name}")
def report(contract_name: str, authorization: str | None = Header(default=None)):
    _auth(authorization)
    with db.get_session() as s:
        row = contract_row(s, contract_name)
        contract = load_contract(row.yaml)
        metrics = s.execute(
            sa.select(db.consistency_metrics, db.runs.c.t)
            .select_from(db.consistency_metrics.join(
                db.runs, db.consistency_metrics.c.run_id == db.runs.c.id))
            .join(db.experiment_plans, db.runs.c.plan_fk == db.experiment_plans.c.id)
            .where(db.experiment_plans.c.contract_id == row.id)
            .order_by(db.runs.c.t)
        ).mappings().all()
        gates = s.execute(
            sa.select(db.gate_decisions, db.runs.c.t, db.runs.c.sut,
                      db.runs.c.created_at.label("run_created_at"))
            .select_from(db.gate_decisions.join(
                db.runs, db.gate_decisions.c.run_id == db.runs.c.id))
            .where(db.gate_decisions.c.contract_id == row.id)
            .order_by(db.gate_decisions.c.id)
        ).mappings().all()
        run_ids = [g["run_id"] for g in gates]
        mode_rows = s.execute(
            sa.select(db.outcome_modes).where(db.outcome_modes.c.run_id.in_(run_ids))
        ).mappings().all() if run_ids else []

    # Charts are drawn from the accumulated per-run series once the baseline window is warm.
    flip_series = [max(g["worst_flip_rate"], 0.0) for g in gates]
    malformed_series = [float(g["evidence"].get("worst_malformed_rate", 0.0)) for g in gates]
    flip_chart = control_chart(flip_series)
    series = [{"index": i, "run_id": g["run_id"], "t": g["t"], "sut": g["sut"],
               "decision": g["decision"], "worst_flip_rate": g["worst_flip_rate"],
               "worst_malformed_rate": malformed_series[i],
               "reasons": g["evidence"].get("reasons", []),
               "created_at": g["run_created_at"]} for i, g in enumerate(gates)]
    latest_run = run_ids[-1] if run_ids else None
    skipped = gates[-1]["evidence"].get("skipped", []) if gates else []

    return {
        "contract": contract_name,
        "subject": row.subject,
        "plan_id": row.plan_id,
        "runs": len(gates),
        "gate_policy": contract.gate.model_dump(mode="json", exclude_none=True),
        "latest_gate": {k: v for k, v in gates[-1].items()
                        if k not in ("t", "sut", "run_created_at")} if gates else None,
        "metrics": [dict(m) for m in metrics],
        "series": series,
        "chart": flip_chart,
        "charts": {
            "flip": flip_chart,
            "malformed": control_chart(malformed_series, p_chart_n=contract.run_policy.samples),
        },
        "mode_noise_floor": mode_engine.MODE_NOISE_FLOOR,
        "mode_window": MODE_WINDOW,
        "modes": _mode_topology(
            list(mode_rows), {rid: i for i, rid in enumerate(run_ids)},
            {g["run_id"]: g["t"] for g in gates}),
        "matrix": invariant_matrix(
            contract, [m for m in metrics if m["run_id"] == latest_run],
            [m for m in mode_rows if m["run_id"] == latest_run]),
        "notes": [f"{c['probe']} / {c['perturbation']}: {c['reason']}" for c in skipped],
    }
