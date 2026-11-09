"""The dashboard's API: overview, contract and run detail, the simulator catalog, the
judge panel, paraphrase generation, and the committed golden-set reports.

Every route takes the bearer token (scripts/gate.py route_auth enforces the class). The
routes read what the run loop stored, or compute from it with the engine. None of them
makes up a number: an empty table is returned as empty.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import sqlalchemy as sa
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from . import db
from .config import settings
from .engine import judges as judge_engine
from .engine.contracts import compile_plan, load_contract
from .engine.embedding import HashingEmbedder
from .engine.metamorphic import generate_paraphrases
from .engine.suts import SUT_CATALOG
from .routes import _auth, contract_row, control_chart, invariant_matrix

router = APIRouter(prefix="/api/v1")

REPO = Path(__file__).resolve().parent.parent
_SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{0,80}$")
GOLDEN_FILES = ("run", "calibration", "drift")


# --------------------------------------------------------------------------- #
# overview, contracts, runs
# --------------------------------------------------------------------------- #
def _contract_summaries(session) -> list[dict]:
    """Every contract with its run count, latest gate decision and chart alarm state."""
    contracts = session.execute(sa.select(db.contracts).order_by(db.contracts.c.name)).all()
    gates = session.execute(
        sa.select(db.gate_decisions, db.runs.c.t, db.runs.c.sut)
        .select_from(db.gate_decisions.join(db.runs, db.gate_decisions.c.run_id == db.runs.c.id))
        .order_by(db.gate_decisions.c.id)
    ).mappings().all()
    by_contract: dict[int, list] = {}
    for g in gates:
        by_contract.setdefault(g["contract_id"], []).append(g)
    out = []
    for c in contracts:
        mine = by_contract.get(c.id, [])
        chart = control_chart([max(g["worst_flip_rate"], 0.0) for g in mine])
        latest = mine[-1] if mine else None
        out.append({
            "name": c.name, "subject": c.subject, "plan_id": c.plan_id,
            "created_at": c.created_at, "runs": len(mine),
            "latest": None if latest is None else {
                "run_id": latest["run_id"], "decision": latest["decision"],
                "worst_flip_rate": latest["worst_flip_rate"], "threshold": latest["threshold"],
                "t": latest["t"], "sut": latest["sut"],
                "reasons": latest["evidence"].get("reasons", []),
                "created_at": latest["created_at"]},
            "chart_warm": chart["warm"],
            "alarms": sum(1 for p in chart["points"] if p["alarm"]),
            "latest_point_alarm": bool(chart["points"] and chart["points"][-1]["alarm"]),
            "trend": [g["worst_flip_rate"] for g in mine[-24:]],
        })
    return out


@router.get("/overview")
def overview(authorization: str | None = Header(default=None)):
    _auth(authorization)
    with db.get_session() as s:
        summaries = _contract_summaries(s)
        latest_runs = [c["latest"]["run_id"] for c in summaries if c["latest"]]
        # Cells of each contract's LATEST run. Counting every cell of every past run
        # would grow forever and say nothing about the state of the board now.
        second_modes = s.execute(
            sa.select(sa.func.count()).select_from(db.outcome_modes)
            .where(db.outcome_modes.c.second_mode_detected.is_(True),
                   db.outcome_modes.c.run_id.in_(latest_runs))).scalar_one() if latest_runs else 0
        judges = _judge_states(s)
    with_runs = [c for c in summaries if c["latest"]]
    return {
        "contracts": len(summaries),
        "runs": sum(c["runs"] for c in summaries),
        "passing": sum(1 for c in with_runs if c["latest"]["decision"] == "pass"),
        "blocked": sum(1 for c in with_runs if c["latest"]["decision"] == "block"),
        "never_run": len(summaries) - len(with_runs),
        "alarms": sum(c["alarms"] for c in summaries),
        "cells_with_second_mode": second_modes,
        "judges": {"total": len(judges),
                   "quarantined": sum(1 for j in judges if j["quarantined"])},
        "latest": summaries,
    }


@router.get("/contracts")
def list_contracts(authorization: str | None = Header(default=None)):
    _auth(authorization)
    with db.get_session() as s:
        return {"contracts": _contract_summaries(s)}


@router.get("/contracts/{name}")
def contract_detail(name: str, authorization: str | None = Header(default=None)):
    _auth(authorization)
    with db.get_session() as s:
        row = contract_row(s, name)
        variants = s.execute(
            sa.select(db.probes.c.probe_key, db.probe_variants)
            .select_from(db.probe_variants.join(
                db.probes, db.probe_variants.c.probe_id == db.probes.c.id))
            .where(db.probes.c.contract_id == row.id).order_by(db.probe_variants.c.id)
        ).mappings().all()
    contract = load_contract(row.yaml)
    plan = compile_plan(contract)
    return {
        "name": row.name, "subject": row.subject, "plan_id": row.plan_id,
        "created_at": row.created_at, "yaml": row.yaml,
        "invariants": [i.model_dump(mode="json", exclude_none=True) for i in contract.invariants],
        "allowed_variation": [a.model_dump() for a in contract.allowed_variation],
        "run_policy": contract.run_policy.model_dump(),
        "gate": contract.gate.model_dump(mode="json", exclude_none=True),
        "probes": [{"id": p.id, "input": p.input, "ladder": p.ladder} for p in contract.probes],
        "plan": [e.model_dump(mode="json") for e in plan.entries],
        "variants": [{"probe": v["probe_key"], "perturbation": v["perturbation"],
                      "text": v["variant_input"], "back_check_score": v["back_check_score"],
                      "accepted": v["accepted"]} for v in variants],
    }


@router.get("/runs/{run_id}")
def run_detail(run_id: int, authorization: str | None = Header(default=None)):
    _auth(authorization)
    with db.get_session() as s:
        found = s.execute(
            sa.select(db.runs, db.contracts.c.name.label("contract"),
                      db.contracts.c.yaml.label("yaml"))
            .select_from(db.runs.join(
                db.experiment_plans, db.runs.c.plan_fk == db.experiment_plans.c.id)
                .join(db.contracts, db.experiment_plans.c.contract_id == db.contracts.c.id))
            .where(db.runs.c.id == run_id)
        ).mappings().first()
        if found is None:
            raise HTTPException(status_code=404, detail="run not found")
        metrics = s.execute(sa.select(db.consistency_metrics)
                            .where(db.consistency_metrics.c.run_id == run_id)
                            .order_by(db.consistency_metrics.c.id)).mappings().all()
        modes = s.execute(sa.select(db.outcome_modes)
                          .where(db.outcome_modes.c.run_id == run_id)
                          .order_by(db.outcome_modes.c.id)).mappings().all()
        gate = s.execute(sa.select(db.gate_decisions)
                         .where(db.gate_decisions.c.run_id == run_id)).mappings().first()
    contract = load_contract(found["yaml"])
    return {
        "run_id": run_id, "contract": found["contract"], "t": found["t"],
        "seed": found["seed"], "sut": found["sut"], "embedder": found["embedder"],
        "created_at": found["created_at"],
        "simulator": SUT_CATALOG.get(found["sut"]),
        "gate": None if gate is None else {
            "decision": gate["decision"], "worst_flip_rate": gate["worst_flip_rate"],
            "threshold": gate["threshold"], "evidence": gate["evidence"]},
        "matrix": invariant_matrix(contract, list(metrics), list(modes)),
        "modes": [{"probe": m["probe_key"], "perturbation": m["perturbation"], "n": m["n"],
                   "modes": m["modes"], "second_mode_share": m["second_mode_share"],
                   "second_mode_detected": m["second_mode_detected"]} for m in modes],
    }


@router.get("/suts")
def simulators(authorization: str | None = Header(default=None)):
    _auth(authorization)
    return {"kind": "simulator",
            "note": "In-process simulators with planted defects. Not measurements of a real system.",
            "suts": [{"name": name, **entry} for name, entry in SUT_CATALOG.items()]}


# --------------------------------------------------------------------------- #
# paraphrase variants: the model proposes, the back-check disposes
# --------------------------------------------------------------------------- #
class VariantsIn(BaseModel):
    contract: str
    probe: str
    n: int = Field(default=5, ge=1, le=20)


def _gateway():
    from groundwork.gateway import LLMGateway  # imported on use: needs a configured key

    return LLMGateway()


@router.post("/probes/variants", status_code=201)
def generate_variants(body: VariantsIn, authorization: str | None = Header(default=None)):
    _auth(authorization)
    if not settings.llm_model_extraction or not settings.openrouter_api_key:
        raise HTTPException(
            status_code=503,
            detail="paraphrase generation needs OPENROUTER_API_KEY and LLM_MODEL_EXTRACTION; "
                   "neither is guessed")
    with db.get_session() as s, s.begin():
        row = contract_row(s, body.contract)
        probe = s.execute(sa.select(db.probes).where(
            db.probes.c.contract_id == row.id, db.probes.c.probe_key == body.probe)).first()
        if probe is None:
            raise HTTPException(status_code=404, detail="probe not found in this contract")
        variants = generate_paraphrases(
            _gateway(), settings.llm_model_extraction, probe.input, body.n, HashingEmbedder())
        for v in variants:
            s.execute(db.probe_variants.insert().values(
                probe_id=probe.id, perturbation="paraphrase", variant_input=v.text,
                back_check_score=v.back_check_score, accepted=v.accepted))
    return {"contract": body.contract, "probe": body.probe,
            "accepted": sum(1 for v in variants if v.accepted),
            "rejected": sum(1 for v in variants if not v.accepted),
            "variants": [{"text": v.text, "back_check_score": v.back_check_score,
                          "accepted": v.accepted, "reason": v.reason} for v in variants]}


# --------------------------------------------------------------------------- #
# judge panel
# --------------------------------------------------------------------------- #
class CalibrationIn(BaseModel):
    judge: str = Field(min_length=1, max_length=120)
    verdicts: dict[str, str]


class PanelIn(BaseModel):
    votes: dict[str, str]
    quorum: int = Field(default=judge_engine.DEFAULT_QUORUM, ge=1, le=25)


def _anchor_path() -> Path:
    path = Path(settings.judge_anchor_set_path)
    return path if path.is_absolute() else REPO / path


def _anchors() -> dict[str, str]:
    try:
        return judge_engine.load_anchors(_anchor_path())
    except (OSError, ValueError) as e:
        raise HTTPException(status_code=503, detail=f"anchor set unavailable: {e}") from e


def _judge_states(session) -> list[dict]:
    rows = session.execute(sa.select(db.judge_calibrations).order_by(
        db.judge_calibrations.c.judge, db.judge_calibrations.c.round)).mappings().all()
    by_judge: dict[str, list] = {}
    for r in rows:
        by_judge.setdefault(r["judge"], []).append(r)
    return [{"judge": judge, "rounds": [dict(r) for r in history],
             "latest_rate": history[-1]["rate"], "latest_kappa": history[-1]["kappa"],
             "quarantined": history[-1]["quarantined"], "reason": history[-1]["reason"]}
            for judge, history in sorted(by_judge.items())]


@router.get("/judges/calibration")
def judge_calibration(authorization: str | None = Header(default=None)):
    _auth(authorization)
    anchors = _anchors()
    with db.get_session() as s:
        judges = _judge_states(s)
    return {"anchors": {"count": len(anchors), "labels": sorted(set(anchors.values())),
                        "ids": sorted(anchors), "source": _anchor_path().name},
            "floor": judge_engine.AGREEMENT_FLOOR,
            "drift_baseline": judge_engine.DRIFT_BASELINE,
            "judges": judges}


@router.post("/judges/calibration", status_code=201)
def record_calibration(body: CalibrationIn, authorization: str | None = Header(default=None)):
    _auth(authorization)
    try:
        result = judge_engine.agreement(body.verdicts, _anchors())
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    with db.get_session() as s, s.begin():
        history = [r.rate for r in s.execute(
            sa.select(db.judge_calibrations.c.rate)
            .where(db.judge_calibrations.c.judge == body.judge)
            .order_by(db.judge_calibrations.c.round)).all()]
        quarantined, reason = judge_engine.quarantine(history + [result.rate], result.n)
        s.execute(db.judge_calibrations.insert().values(
            judge=body.judge, round=len(history) + 1, n=result.n, agree=result.agree,
            rate=result.rate, kappa=result.kappa, quarantined=quarantined, reason=reason))
    return {"judge": body.judge, "round": len(history) + 1, "n": result.n,
            "agree": result.agree, "rate": result.rate, "low": result.low,
            "high": result.high, "kappa": result.kappa,
            "quarantined": quarantined, "reason": reason}


@router.post("/judges/panel")
def judge_panel(body: PanelIn, authorization: str | None = Header(default=None)):
    """Panel verdict over the submitted votes. A judge with no calibration on record is
    excluded exactly like a quarantined one: an unmeasured instrument is not trusted."""
    _auth(authorization)
    if not body.votes:
        raise HTTPException(status_code=422, detail="a panel needs at least one vote")
    with db.get_session() as s:
        states = {j["judge"]: j for j in _judge_states(s)}
    status = {}
    for judge in sorted(body.votes):
        state = states.get(judge)
        if state is None:
            status[judge] = "uncalibrated"
        else:
            status[judge] = state["reason"] if state["quarantined"] else "active"
    excluded = {j for j, st in status.items() if st != "active"}
    verdict = judge_engine.panel_verdict(body.votes, excluded, quorum=body.quorum)
    return {"label": verdict.label, "reason": verdict.reason,
            "counted": list(verdict.counted), "excluded": list(verdict.excluded),
            "judges": status}


# --------------------------------------------------------------------------- #
# golden-set reports: files a `seismo run|calibrate|drift` wrote and someone committed
# --------------------------------------------------------------------------- #
def _reports_dir() -> Path:
    path = Path(settings.reports_dir)
    return path if path.is_absolute() else REPO / path


def _read_report(directory: Path, kind: str) -> dict | None:
    path = directory / f"{kind}.json"
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


@router.get("/golden")
def golden_index(authorization: str | None = Header(default=None)):
    _auth(authorization)
    root = _reports_dir()
    out = []
    for directory in sorted(p for p in root.iterdir() if p.is_dir()) if root.is_dir() else []:
        run = _read_report(directory, "run")
        if run is None:
            continue
        out.append({"contract": directory.name, "model": run.get("model"),
                    "kind": run.get("kind"), "passed": run.get("passed"),
                    "probes": run.get("probes"), "records": run.get("records"),
                    "run_at": run.get("run_at"),
                    "available": [k for k in GOLDEN_FILES if (directory / f"{k}.json").is_file()]})
    return {"reports": out}


@router.get("/golden/{contract}")
def golden_detail(contract: str, authorization: str | None = Header(default=None)):
    _auth(authorization)
    if not _SLUG.match(contract):
        raise HTTPException(status_code=404, detail="no golden-set report by that name")
    directory = _reports_dir() / contract
    reports = {kind: _read_report(directory, kind) for kind in GOLDEN_FILES}
    if reports["run"] is None:
        raise HTTPException(status_code=404, detail="no golden-set report by that name")
    return {"contract": contract, **reports}
