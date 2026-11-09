"""The dashboard's API, end to end against a real (in-memory) database.

Every assertion is on data the run loop stored. The empty states matter as much as the
full ones: a board with nothing on it must say so, not show a green zero.
"""
import json
from pathlib import Path

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient

from app import db, read_api
from app.config import settings
from app.main import app

ROOT = Path(__file__).resolve().parent.parent
CONTRACT_YAML = (ROOT / "data" / "synthetic" / "contract.yaml").read_text(encoding="utf-8")
NAME = "refund-decision-stability"

FULL_YAML = """
contract: refund-full
subject: support-agent
invariants:
  - field: eligibility_decision
    under: [repeat_run, irrelevant_context, reordering, format, paraphrase]
    relation: equal
  - field: cited_policy_ids
    under: [repeat_run]
    relation: jaccard_at_least
    threshold: 0.85
allowed_variation:
  - field: response_wording
    rule: semantically_equivalent
run_policy: {samples: 20, configs: 1, confidence: 0.95}
gate: {max_decision_flip_rate: 0.15, max_malformed_rate: 0.05}
probes:
  - id: refund-basic
    input: "Customer bought a blender 12 days ago, unopened. Are they refund eligible?"
"""


@pytest.fixture()
def client():
    engine = sa.create_engine("sqlite://", poolclass=sa.pool.StaticPool,
                              connect_args={"check_same_thread": False})
    db.metadata.create_all(engine)
    db.set_engine_for_tests(engine)
    return TestClient(app)


def _register(client, yaml=CONTRACT_YAML):
    assert client.post("/api/v1/contracts", json={"yaml": yaml}).status_code == 201


def _run(client, contract=NAME, **body):
    r = client.post("/api/v1/runs", json={"contract": contract, **body})
    assert r.status_code == 201, r.text
    return r.json()


# --------------------------------------------------------------------------- #
# empty states
# --------------------------------------------------------------------------- #
def test_an_empty_instance_reports_zeros_not_green():
    c = TestClient(app)
    engine = sa.create_engine("sqlite://", poolclass=sa.pool.StaticPool,
                              connect_args={"check_same_thread": False})
    db.metadata.create_all(engine)
    db.set_engine_for_tests(engine)
    body = c.get("/api/v1/overview").json()
    assert body == {"contracts": 0, "runs": 0, "passing": 0, "blocked": 0, "never_run": 0,
                    "alarms": 0, "cells_with_second_mode": 0,
                    "judges": {"total": 0, "quarantined": 0}, "latest": []}
    assert c.get("/api/v1/contracts").json() == {"contracts": []}


def test_a_registered_contract_with_no_runs_is_never_run_not_passing(client):
    _register(client)
    body = client.get("/api/v1/overview").json()
    assert (body["contracts"], body["never_run"], body["passing"]) == (1, 1, 0)
    entry = body["latest"][0]
    assert entry["latest"] is None and entry["runs"] == 0 and entry["trend"] == []
    report = client.get(f"/api/v1/reports/{NAME}").json()
    assert report["runs"] == 0 and report["latest_gate"] is None
    assert report["series"] == [] and report["modes"] == [] and report["matrix"] == []
    assert report["chart"]["runs_until_warm"] == 9


# --------------------------------------------------------------------------- #
# run loop -> report
# --------------------------------------------------------------------------- #
def test_a_run_returns_its_reasons_cells_and_skipped_paraphrase_cells(client):
    _register(client)
    body = _run(client)
    assert body["gate"] == "pass" and body["reasons"] == [] and body["worst_cell"] is None
    assert body["skipped"] == [
        {"probe": p, "perturbation": "paraphrase",
         "reason": "no accepted paraphrase variants generated yet"}
        for p in ("refund-basic", "refund-edge")]
    report = client.get(f"/api/v1/reports/{NAME}").json()
    assert len(report["notes"]) == 2 and "paraphrase" in report["notes"][0]
    assert report["subject"] == "support-agent"
    assert report["gate_policy"] == {"max_decision_flip_rate": 0.01, "max_malformed_rate": 0.0}


def test_the_chart_warms_after_the_baseline_and_alarms_on_the_planted_jump(client):
    _register(client, FULL_YAML)
    for t in range(18):
        _run(client, "refund-full", sut="jump", t=t, seed=11)
    report = client.get("/api/v1/reports/refund-full").json()
    flip = report["charts"]["flip"]
    assert flip["warm"] is True and flip["runs_until_warm"] == 0
    assert [p["t"] for p in flip["points"]] == list(range(8, 18))
    before = [p for p in flip["points"] if p["t"] < 12]
    after = [p for p in flip["points"] if p["t"] >= 12]
    assert not any(p["alarm"] for p in before), "healthy points must stay quiet"
    assert all(p["alarm"] and p["rule"] == "we1" for p in after), "the jump must alarm"
    assert report["chart"] == flip
    assert report["series"][-1]["decision"] == "block"
    assert report["series"][-1]["sut"] == "jump"
    assert "flip rate" in report["series"][-1]["reasons"][0]
    assert report["latest_gate"]["decision"] == "block" and "sut" not in report["latest_gate"]

    summary = client.get("/api/v1/contracts").json()["contracts"][0]
    assert summary["chart_warm"] and summary["alarms"] == len(after)
    assert summary["latest_point_alarm"] is True and len(summary["trend"]) == 18
    overview = client.get("/api/v1/overview").json()
    assert (overview["blocked"], overview["passing"], overview["alarms"]) == (1, 0, len(after))


def test_the_malformed_chart_is_a_p_chart_over_the_contract_sample_size(client):
    _register(client, FULL_YAML)
    for t in range(16):
        _run(client, "refund-full", sut="flaky", t=t, seed=5)
    malformed = client.get("/api/v1/reports/refund-full").json()["charts"]["malformed"]
    assert malformed["warm"] is True
    assert all(p["lcl"] == 0.0 for p in malformed["points"])
    assert any(p["alarm"] for p in malformed["points"] if p["t"] >= 12)


def test_the_invariant_matrix_names_the_violated_cell(client):
    _register(client, FULL_YAML)
    run = _run(client, "refund-full", sut="distractible")
    assert run["worst_cell"] == {"probe": "refund-basic", "perturbation": "irrelevant_context",
                                 "field": "eligibility_decision"}
    matrix = client.get("/api/v1/reports/refund-full").json()["matrix"]
    violated = {row["perturbation"] for row in matrix if row["violated"]}
    assert violated == {"irrelevant_context"}
    assert {row["perturbation"] for row in matrix} == {
        "repeat_run", "irrelevant_context", "reordering", "format"}


def test_mode_topology_pools_a_window_and_finds_the_planted_second_mode(client):
    _register(client, FULL_YAML)
    for t in range(12, 26):
        _run(client, "refund-full", sut="bimodal", t=t, seed=3)
    report = client.get("/api/v1/reports/refund-full").json()
    cell = next(c for c in report["modes"] if c["perturbation"] == "repeat_run")
    assert cell["window"] == 12 and len(cell["by_run"]) == 14
    pooled = cell["pooled"]
    assert pooled["n"] == 12 * 20 and len(pooled["modes"]) == 2
    assert pooled["second_mode_detected"] is True
    assert pooled["modes"][1]["signature"]["cited_policy_ids"] == ["POL-12", "POL-7"]
    # the decision never flipped: the flip chart saw nothing
    assert {s["worst_flip_rate"] for s in report["series"]} == {0.0}
    shares = cell["by_run"][0]["shares"]
    assert abs(sum(shares.values()) - 1.0) < 1e-9
    assert client.get("/api/v1/overview").json()["cells_with_second_mode"] >= 1


def test_run_detail_carries_the_gate_evidence_matrix_modes_and_simulator_label(client):
    _register(client, FULL_YAML)
    run = _run(client, "refund-full", sut="format-sensitive", t=4, seed=9)
    body = client.get(f"/api/v1/runs/{run['run_id']}").json()
    assert (body["contract"], body["t"], body["seed"], body["sut"]) == (
        "refund-full", 4, 9, "format-sensitive")
    assert body["simulator"]["planted_defect"] == "format"
    assert body["gate"]["decision"] == "block"
    assert body["gate"]["evidence"]["worst_cell"]["perturbation"] == "format"
    assert len(body["matrix"]) == 4 and len(body["modes"]) == 4
    assert client.get("/api/v1/runs/99999").status_code == 404


def test_contract_detail_exposes_the_plan_the_yaml_and_the_probes(client):
    _register(client, FULL_YAML)
    body = client.get("/api/v1/contracts/refund-full").json()
    assert body["yaml"] == FULL_YAML
    assert [e["perturbation"] for e in body["plan"]] == [
        "format", "irrelevant_context", "paraphrase", "reordering", "repeat_run"]
    assert body["gate"] == {"max_decision_flip_rate": 0.15, "max_malformed_rate": 0.05}
    assert body["probes"][0]["ladder"] is None and body["variants"] == []
    assert body["run_policy"]["samples"] == 20
    assert client.get("/api/v1/contracts/nope").status_code == 404


def test_the_simulator_catalog_is_labelled_as_simulators(client):
    body = client.get("/api/v1/suts").json()
    assert body["kind"] == "simulator" and "Not measurements" in body["note"]
    names = {s["name"] for s in body["suts"]}
    assert {"stable", "drift", "bimodal", "non-monotonic"} <= names
    assert all("summary" in s and "planted_defect" in s for s in body["suts"])


# --------------------------------------------------------------------------- #
# paraphrase variants
# --------------------------------------------------------------------------- #
class FakeGateway:
    def __init__(self, paraphrases):
        self.paraphrases = paraphrases

    def complete(self, *, model, messages, json_schema):
        return {"paraphrases": self.paraphrases}


def test_variant_generation_refuses_to_guess_a_model(client, monkeypatch):
    _register(client, FULL_YAML)
    monkeypatch.setattr(settings, "llm_model_extraction", "")
    r = client.post("/api/v1/probes/variants", json={"contract": "refund-full", "probe": "refund-basic"})
    assert r.status_code == 503 and "neither is guessed" in r.json()["detail"]


def test_generated_variants_are_back_checked_stored_and_then_executed(client, monkeypatch):
    _register(client, FULL_YAML)
    monkeypatch.setattr(settings, "llm_model_extraction", "test/model")
    monkeypatch.setattr(settings, "openrouter_api_key", "test-key")
    good = "A customer bought a blender 12 days ago and it is unopened. Are they refund eligible?"
    drifted = "Customer bought a blender 120 days ago, unopened. Are they refund eligible?"
    monkeypatch.setattr(read_api, "_gateway", lambda: FakeGateway([good, drifted, ""]))

    r = client.post("/api/v1/probes/variants", json={"contract": "refund-full", "probe": "refund-basic", "n": 3})
    assert r.status_code == 201, r.text
    body = r.json()
    assert (body["accepted"], body["rejected"]) == (1, 2)
    assert {v["reason"] for v in body["variants"]} == {"ok", "numeric_drift", "empty"}

    detail = client.get("/api/v1/contracts/refund-full").json()
    assert [v["accepted"] for v in detail["variants"]] == [True, False, False]

    run = _run(client, "refund-full", sut="policy")
    assert run["skipped"] == [] and run["cells"] == 5 and run["gate"] == "pass"


def test_variant_generation_404s_on_an_unknown_contract_or_probe(client, monkeypatch):
    _register(client, FULL_YAML)
    monkeypatch.setattr(settings, "llm_model_extraction", "test/model")
    monkeypatch.setattr(settings, "openrouter_api_key", "test-key")
    monkeypatch.setattr(read_api, "_gateway", lambda: FakeGateway([]))
    assert client.post("/api/v1/probes/variants",
                       json={"contract": "nope", "probe": "x"}).status_code == 404
    assert client.post("/api/v1/probes/variants",
                       json={"contract": "refund-full", "probe": "x"}).status_code == 404


def test_the_real_gateway_factory_is_the_groundwork_gateway(monkeypatch):
    import groundwork.gateway

    monkeypatch.setattr(groundwork.gateway, "LLMGateway", lambda: "gateway-instance")
    assert read_api._gateway() == "gateway-instance"


# --------------------------------------------------------------------------- #
# judge panel
# --------------------------------------------------------------------------- #
def _anchors() -> dict[str, str]:
    raw = json.loads((ROOT / "data" / "checks" / "judge_agreement_set.v1.json").read_text(encoding="utf-8"))
    return {i["id"]: i["gold_label"] for i in raw["items"] if "gold_label" in i}


def _calibrate(client, judge: str, wrong: int = 0):
    verdicts = dict(_anchors())
    for key in sorted(verdicts)[:wrong]:
        verdicts[key] = "clean" if verdicts[key] != "clean" else "planted"
    return client.post("/api/v1/judges/calibration", json={"judge": judge, "verdicts": verdicts})


def test_calibration_starts_empty_and_describes_its_anchor_set(client):
    body = client.get("/api/v1/judges/calibration").json()
    assert body["judges"] == [] and body["floor"] == 0.8 and body["drift_baseline"] == 8
    assert body["anchors"]["count"] == len(_anchors()) == len(body["anchors"]["ids"])
    assert body["anchors"]["labels"] == ["clean", "planted"]
    assert body["anchors"]["source"] == "judge_agreement_set.v1.json"


def test_a_calibration_round_is_scored_stored_and_numbered(client):
    first = _calibrate(client, "judge-a").json()
    assert (first["round"], first["rate"], first["quarantined"], first["reason"]) == (1, 1.0, False, None)
    assert first["n"] == first["agree"] == len(_anchors()) and first["kappa"] == 1.0
    second = _calibrate(client, "judge-a", wrong=4).json()
    assert second["round"] == 2 and second["rate"] == pytest.approx(0.6)
    assert (second["quarantined"], second["reason"]) == (True, "below_floor")
    judges = client.get("/api/v1/judges/calibration").json()["judges"]
    assert len(judges) == 1 and len(judges[0]["rounds"]) == 2
    assert judges[0]["quarantined"] is True and judges[0]["latest_rate"] == pytest.approx(0.6)
    assert client.get("/api/v1/overview").json()["judges"] == {"total": 1, "quarantined": 1}


def test_unknown_anchor_ids_are_a_422_and_nothing_is_stored(client):
    r = client.post("/api/v1/judges/calibration",
                    json={"judge": "judge-a", "verdicts": {"not-an-anchor": "clean"}})
    assert r.status_code == 422 and "not-an-anchor" in r.json()["detail"]
    assert client.get("/api/v1/judges/calibration").json()["judges"] == []


def test_a_missing_anchor_set_is_a_503_not_an_empty_panel(client, monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "judge_anchor_set_path", str(tmp_path / "missing.json"))
    r = client.get("/api/v1/judges/calibration")
    assert r.status_code == 503 and "anchor set unavailable" in r.json()["detail"]


def test_the_panel_counts_active_judges_and_names_the_excluded(client):
    _calibrate(client, "judge-a")
    _calibrate(client, "judge-b")
    _calibrate(client, "judge-c", wrong=5)          # quarantined: below_floor
    votes = {"judge-a": "clean", "judge-b": "clean", "judge-c": "planted", "judge-new": "planted"}
    body = client.post("/api/v1/judges/panel", json={"votes": votes}).json()
    assert body["label"] == "clean" and body["counted"] == ["judge-a", "judge-b"]
    assert body["excluded"] == ["judge-c", "judge-new"]
    assert body["judges"] == {"judge-a": "active", "judge-b": "active",
                              "judge-c": "below_floor", "judge-new": "uncalibrated"}
    assert body["reason"] == "2 of 2 active judges"


def test_a_panel_of_uncalibrated_judges_gives_no_verdict(client):
    body = client.post("/api/v1/judges/panel", json={"votes": {"x": "clean", "y": "clean"}}).json()
    assert body["label"] is None and "quorum is 2" in body["reason"]
    assert client.post("/api/v1/judges/panel", json={"votes": {}}).status_code == 422


# --------------------------------------------------------------------------- #
# golden-set reports
# --------------------------------------------------------------------------- #
@pytest.fixture()
def reports(tmp_path, monkeypatch):
    root = tmp_path / "reports"
    (root / "kalika-qa-gate").mkdir(parents=True)
    (root / "empty-dir").mkdir()
    (root / "stray.md").write_text("not a report directory", encoding="utf-8")
    run = {"contract": "kalika-qa-gate", "model": "jev-1.13", "kind": "noul_flag",
           "passed": True, "probes": 130, "records": 650, "run_at": "2026-09-21T23:06:43Z"}
    (root / "kalika-qa-gate" / "run.json").write_text(json.dumps(run), encoding="utf-8")
    (root / "kalika-qa-gate" / "calibration.json").write_text(
        json.dumps({"expected_calibration_error": 0.084}), encoding="utf-8")
    monkeypatch.setattr(settings, "reports_dir", str(root))
    return root


def test_the_golden_index_lists_only_directories_with_a_run_report(client, reports):
    body = client.get("/api/v1/golden").json()
    assert body == {"reports": [{
        "contract": "kalika-qa-gate", "model": "jev-1.13", "kind": "noul_flag",
        "passed": True, "probes": 130, "records": 650, "run_at": "2026-09-21T23:06:43Z",
        "available": ["run", "calibration"]}]}


def test_golden_detail_returns_each_report_and_null_for_the_missing_one(client, reports):
    body = client.get("/api/v1/golden/kalika-qa-gate").json()
    assert body["run"]["records"] == 650
    assert body["calibration"] == {"expected_calibration_error": 0.084}
    assert body["drift"] is None


@pytest.mark.parametrize("name", ["empty-dir", "nope", "..", "Has.Dots", "%2e%2e"])
def test_golden_detail_404s_without_touching_paths_outside_the_reports_dir(client, reports, name):
    assert client.get(f"/api/v1/golden/{name}").status_code == 404


def test_a_missing_reports_directory_is_an_empty_index(client, monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "reports_dir", str(tmp_path / "absent"))
    assert client.get("/api/v1/golden").json() == {"reports": []}


def test_the_committed_reports_are_served_from_the_repo_by_default(client):
    names = {r["contract"] for r in client.get("/api/v1/golden").json()["reports"]}
    assert {"kalika-qa-gate", "skill-routing"} <= names
    detail = client.get("/api/v1/golden/kalika-qa-gate").json()
    assert detail["calibration"]["bins"] and detail["drift"]["control_chart"]["points"]


# --------------------------------------------------------------------------- #
# auth: every dashboard route is bearer-gated when a token is set
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("method,path,body", [
    ("get", "/api/v1/overview", None),
    ("get", "/api/v1/contracts", None),
    ("get", "/api/v1/contracts/x", None),
    ("get", "/api/v1/runs/1", None),
    ("get", "/api/v1/suts", None),
    ("post", "/api/v1/probes/variants", {"contract": "x", "probe": "y"}),
    ("get", "/api/v1/judges/calibration", None),
    ("post", "/api/v1/judges/calibration", {"judge": "j", "verdicts": {}}),
    ("post", "/api/v1/judges/panel", {"votes": {"a": "b"}}),
    ("get", "/api/v1/golden", None),
    ("get", "/api/v1/golden/x", None),
])
def test_every_dashboard_route_requires_the_bearer_token(client, monkeypatch, method, path, body):
    monkeypatch.setattr(settings, "smoke_test_token", "sekrit")
    call = getattr(client, method)
    kwargs = {"json": body} if body is not None else {}
    assert call(path, **kwargs).status_code == 401
    authed = call(path, headers={"Authorization": "Bearer sekrit"}, **kwargs)
    assert authed.status_code != 401
