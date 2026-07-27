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


PARAPHRASE_ONLY_YAML = """
contract: paraphrase-only
subject: support-agent
invariants:
  - field: eligibility_decision
    under: [paraphrase]
    relation: equal
run_policy: {samples: 5, configs: 1, confidence: 0.9}
gate: {max_decision_flip_rate: 0.05}
probes:
  - id: p1
    input: "Customer bought a blender 12 days ago, unopened. Are they refund eligible?"
"""


def test_zero_cell_run_is_422_not_a_recorded_pass(client):
    # A contract whose only cells are paraphrase (no generated variants yet) must not
    # produce a gate decision over zero measurements (Standard 3: never silently skipped).
    assert client.post("/api/v1/contracts",
                       json={"yaml": PARAPHRASE_ONLY_YAML}).status_code == 201
    r = client.post("/api/v1/runs", json={"contract": "paraphrase-only"})
    assert r.status_code == 422
    assert "no executable plan cells" in r.json()["detail"]


def test_cli_refuses_zero_cell_contract(tmp_path):
    from app import cli
    p = tmp_path / "contract.yaml"
    p.write_text(PARAPHRASE_ONLY_YAML, encoding="utf-8")
    assert cli.run(str(p), "stable", points=3, seed=7, report_path=None) == 2


def test_malformed_output_blocks_gate(client, monkeypatch):
    # 100% wording-malformed output must block even though flip_rate over the (empty)
    # parsed set is 0.0 — the FlakySUT defect class gates directly on malformed rate.
    from app.engine.suts import DEMO_SUTS, FlakySUT
    monkeypatch.setitem(DEMO_SUTS, "flaky", FlakySUT(onset=0, p=0.5, burst=10**6))
    assert client.post("/api/v1/contracts", json={"yaml": CONTRACT_YAML}).status_code == 201
    r = client.post("/api/v1/runs",
                    json={"contract": "refund-decision-stability", "sut": "flaky"})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["worst_malformed_rate"] > 0.0
    assert body["gate"] == "block"


class VaryingPoliciesSUT:
    """Constant decision, unstable policy citations: violates jaccard_at_least only."""

    name = "varying"

    def run(self, probe_input, t, rng):
        import json
        policies = ["POL-7"] if rng.random() < 0.5 else ["POL-9"]
        return json.dumps({"eligibility_decision": "eligible",
                           "cited_policy_ids": policies,
                           "response_wording": "Refund decision per policy."})


def test_jaccard_threshold_below_declared_blocks_gate(client, monkeypatch):
    # The contract declares jaccard_at_least 0.85 on cited_policy_ids; a SUT that cites
    # unstable policies must block even with a perfectly stable decision (flip 0.0).
    from app.engine.suts import DEMO_SUTS
    monkeypatch.setitem(DEMO_SUTS, "varying", VaryingPoliciesSUT())
    assert client.post("/api/v1/contracts", json={"yaml": CONTRACT_YAML}).status_code == 201
    r = client.post("/api/v1/runs",
                    json={"contract": "refund-decision-stability", "sut": "varying"})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["worst_flip_rate"] == 0.0
    assert body["jaccard_failures"], "declared jaccard threshold was not enforced"
    assert body["gate"] == "block"


def test_registration_race_loser_gets_409(client, monkeypatch):
    # Simulate the loser of a concurrent registration race: the pre-check misses, the
    # unique index catches the duplicate INSERT — documented contract is still 409.
    import sqlalchemy as sa_real
    from app import routes
    assert client.post("/api/v1/contracts", json={"yaml": CONTRACT_YAML}).status_code == 201
    real_select = sa_real.select
    monkeypatch.setattr(
        routes.sa, "select",
        lambda *args, **kw: real_select(*args, **kw).where(sa_real.false()))
    r = client.post("/api/v1/contracts", json={"yaml": CONTRACT_YAML})
    assert r.status_code == 409


def test_production_with_empty_token_refuses_startup(monkeypatch):
    from groundwork import Env
    from app.config import settings
    from app.main import require_production_auth
    monkeypatch.setattr(settings, "app_env", Env.production)
    monkeypatch.setattr(settings, "smoke_test_token", "")
    with pytest.raises(RuntimeError, match="SMOKE_TEST_TOKEN"):
        require_production_auth()
    monkeypatch.setattr(settings, "smoke_test_token", "real-token")
    require_production_auth()   # with a token, production starts fine


def test_business_reads_require_bearer_when_token_set(client, monkeypatch):
    """GET the stored report must not be world-readable in production.

    Found by the production business-loop audit: this endpoint served real business
    data to an unauthenticated caller over the public internet. Reads are now gated by
    the same bearer check as writes; auth stays off only while the token is empty
    (development semantics).
    """
    from app.config import settings
    monkeypatch.setattr(settings, "smoke_test_token", "sekrit")
    assert client.get("/api/v1/reports/no-such-contract").status_code == 401
    assert client.get(
        "/api/v1/reports/no-such-contract", headers={"Authorization": "Bearer sekrit"}).status_code != 401


def test_root_serves_a_real_html_page(client):
    """The front door must answer a browser. Every gate passed for hours while this 404ed."""
    r = client.get("/", headers={"Accept": "text/html"})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")
    body = r.text
    assert len(body) > 500
    assert "Seismograph" in body
    for placeholder in ("TODO", "Lorem", "example.com", "XXX"):
        assert placeholder not in body


def test_root_publishes_the_eval_limits_sentence_verbatim():
    """The page quotes EVAL.md, so the two cannot drift apart silently."""
    import re
    from pathlib import Path
    from app.frontpage import render

    eval_md = (Path(__file__).resolve().parent.parent / "EVAL.md").read_text(encoding="utf-8")
    limits = " ".join(re.search(r"<!-- LIMITS -->\s*(.+?)\s*<!-- /LIMITS -->",
                                eval_md, re.S).group(1).split())
    assert limits in " ".join(render().split())


def test_root_reports_unknown_rather_than_a_fake_build_stamp(monkeypatch):
    """No build args means "unknown" on the page, never a plausible-looking placeholder."""
    from app import frontpage
    monkeypatch.delenv("GIT_SHA", raising=False)
    monkeypatch.delenv("APP_VERSION", raising=False)
    frontpage._template.cache_clear()
    body = frontpage.render()
    assert "unknown" in body and "__SHA__" not in body and "__VERSION__" not in body
