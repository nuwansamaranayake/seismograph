"""fixtures.py, schemas.py and main.py edge paths."""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from groundwork import Env
from pydantic import ValidationError

from app import fixtures, main
from app.schemas import DemoResponse


# ---- fixtures -------------------------------------------------------------
def test_fixture_missing_file_fails_loud(monkeypatch, tmp_path):
    monkeypatch.setattr(fixtures, "_DEMO", tmp_path / "absent.json")
    with pytest.raises(NotImplementedError, match="Synthetic demo dataset not found"):
        fixtures.load_synthetic_fixture()


def test_fixture_non_list_rejected(monkeypatch, tmp_path):
    p = tmp_path / "demo.json"
    p.write_text(json.dumps({"a": 1}), encoding="utf-8")
    monkeypatch.setattr(fixtures, "_DEMO", p)
    with pytest.raises(ValueError, match="JSON array"):
        fixtures.load_synthetic_fixture()


def test_fixture_loads_list(monkeypatch, tmp_path):
    p = tmp_path / "demo.json"
    p.write_text(json.dumps([{"k": 1}, {"k": 2}]), encoding="utf-8")
    monkeypatch.setattr(fixtures, "_DEMO", p)
    assert fixtures.load_synthetic_fixture() == [{"k": 1}, {"k": 2}]


def test_real_fixture_is_nonempty_list():
    assert len(fixtures.load_synthetic_fixture()) > 0


# ---- schemas --------------------------------------------------------------
def test_demo_response_accepts_items_and_rejects_bad_shape():
    assert DemoResponse(items=[{"a": 1}]).items == [{"a": 1}]
    with pytest.raises(ValidationError):
        DemoResponse(items="nope")
    with pytest.raises(ValidationError):
        DemoResponse()


# ---- main -----------------------------------------------------------------
def test_demo_returns_items_in_development():
    r = TestClient(main.app).get("/api/v1/demo")
    assert r.status_code == 200
    assert len(r.json()["items"]) > 0


def test_demo_disabled_outside_development(monkeypatch):
    monkeypatch.setattr(main.settings, "app_env", Env.production)
    r = TestClient(main.app).get("/api/v1/demo")
    assert r.status_code == 503
    assert "disabled outside development" in r.json()["detail"]


def test_demo_empty_fixture_is_500(monkeypatch):
    monkeypatch.setattr(main, "load_synthetic_fixture", lambda: [])
    r = TestClient(main.app).get("/api/v1/demo")
    assert r.status_code == 500
    assert "empty" in r.json()["detail"]


def test_health_reports_env():
    r = TestClient(main.app).get("/health")
    assert r.json() == {"status": "ok", "env": "development"}


def test_root_serves_html():
    r = TestClient(main.app).get("/")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")
    assert "__VERSION__" not in r.text


def test_require_production_auth_guard():
    class Cfg:
        app_env = Env.production
        smoke_test_token = ""

    with pytest.raises(RuntimeError, match="SMOKE_TEST_TOKEN is empty"):
        main.require_production_auth(Cfg)
    Cfg.smoke_test_token = "t"
    main.require_production_auth(Cfg)
    Cfg.app_env = Env.development
    Cfg.smoke_test_token = ""
    main.require_production_auth(Cfg)
