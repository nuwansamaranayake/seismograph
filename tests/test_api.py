from pathlib import Path

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient

from app import db
from app.main import app

CONTRACT_YAML = (
    Path(__file__).resolve().parent.parent / "data" / "synthetic" / "contract.yaml"
).read_text(encoding="utf-8")


@pytest.fixture()
def client():
    engine = sa.create_engine(
        "sqlite://",
        poolclass=sa.pool.StaticPool,
        connect_args={"check_same_thread": False},   # TestClient serves on another thread
    )
    db.metadata.create_all(engine)
    db.set_engine_for_tests(engine)
    return TestClient(app)


def test_contract_run_report_loop(client):
    r = client.post("/api/v1/contracts", json={"yaml": CONTRACT_YAML})
    assert r.status_code == 201, r.text
    assert r.json()["entries"] == 4

    r = client.post("/api/v1/runs", json={"contract": "refund-decision-stability"})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["cells"] == 2                       # two probes x repeat_run
    assert body["gate"] == "pass"                   # stable SUT never flips

    r = client.get("/api/v1/reports/refund-decision-stability")
    assert r.status_code == 200
    rep = r.json()
    assert rep["runs"] == 1
    assert len(rep["metrics"]) == 2
    assert rep["latest_gate"]["decision"] == "pass"
    assert rep["chart"]["warm"] is False            # one run cannot warm a chart


def test_duplicate_contract_is_409(client):
    assert client.post("/api/v1/contracts", json={"yaml": CONTRACT_YAML}).status_code == 201
    assert client.post("/api/v1/contracts", json={"yaml": CONTRACT_YAML}).status_code == 409


def test_invalid_contract_is_422(client):
    r = client.post("/api/v1/contracts", json={"yaml": "contract: x\nprobes: []"})
    assert r.status_code == 422


def test_unknown_contract_run_is_404(client):
    r = client.post("/api/v1/runs", json={"contract": "nope"})
    assert r.status_code == 404


def test_bearer_auth_enforced_when_token_set(client, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "smoke_test_token", "sekrit")
    r = client.post("/api/v1/contracts", json={"yaml": CONTRACT_YAML})
    assert r.status_code == 401
    r = client.post("/api/v1/contracts", json={"yaml": CONTRACT_YAML},
                    headers={"Authorization": "Bearer sekrit"})
    assert r.status_code == 201
