from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_ok():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_demo_returns_items_in_development():
    # In development the demo serves the synthetic fixture; smoke-parity in-process.
    r = client.get("/api/v1/demo")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["items"], "demo endpoint returned no items in development"
