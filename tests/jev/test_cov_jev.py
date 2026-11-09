"""Remaining branches of app.jev: env hydration, answer decisions, connection errors."""
from __future__ import annotations

import json
import os
import sys
import types

import httpx2
import pytest

from app import jev
from app.jev import JevAnswer, JevTarget, map_answers
from app.targets import TargetConfigError, TargetError

NAMES = ("TYPESAFE_API_KEY", "TYPESAFE_BASE_URL")


# ------------------------------------------------------------- hydrate ---
class _FakeKey:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _fake_winreg(values):
    mod = types.ModuleType("winreg")
    mod.HKEY_CURRENT_USER = object()

    def open_key(root, sub):
        assert sub == "Environment"
        return _FakeKey()

    def query(key, name):
        if name not in values:
            raise OSError("not found")
        return values[name], 1

    mod.OpenKey = open_key
    mod.QueryValueEx = query
    return mod


def _with_os_name(name, fn):
    old = os.name
    os.name = name
    try:
        return fn()
    finally:
        os.name = old


def test_hydrate_is_a_noop_off_windows(monkeypatch):
    for n in NAMES:
        monkeypatch.delenv(n, raising=False)
    assert _with_os_name("posix", jev.hydrate_env_from_user_scope) == []
    assert all(n not in os.environ for n in NAMES)


def test_hydrate_fills_missing_skips_present_and_unset(monkeypatch):
    monkeypatch.setitem(sys.modules, "winreg", _fake_winreg(
        {"TYPESAFE_API_KEY": "  reg-key  ", "TYPESAFE_BASE_URL": "   "}))
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    monkeypatch.setenv("TYPESAFE_BASE_URL", "https://already.example")
    filled = _with_os_name("nt", jev.hydrate_env_from_user_scope)
    assert filled == ["TYPESAFE_API_KEY"]
    assert os.environ["TYPESAFE_API_KEY"] == "reg-key"
    assert os.environ["TYPESAFE_BASE_URL"] == "https://already.example"


def test_hydrate_ignores_blank_registry_value_and_missing_names(monkeypatch):
    monkeypatch.setitem(sys.modules, "winreg", _fake_winreg({"TYPESAFE_BASE_URL": "  "}))
    for n in NAMES:
        monkeypatch.delenv(n, raising=False)
    assert _with_os_name("nt", jev.hydrate_env_from_user_scope) == []
    assert all(n not in os.environ for n in NAMES)


# ------------------------------------------------------------- answers ---
def test_decision_noul_threshold_and_categorical():
    noul = JevAnswer("q", "noul", 0.6, {"true": 0.6, "false": 0.4}, 0.6)
    assert noul.decision(0.5) is True
    assert noul.decision(0.6) is True
    assert noul.decision(0.61) is False
    choice = JevAnswer("q", "choice", "billing", {"billing": 1.0}, 1.0)
    assert choice.decision(0.99) == "billing"
    score = JevAnswer("q", "score", 2.0, {"0": 1.0}, 1.0)
    assert score.decision(0.0) == "2.0"


def test_missing_or_empty_probabilities_raise():
    q = {"d": {"type": "choice", "instructions": "x", "criteria": {"a": "A", "b": "B"}}}
    for probs in (None, {}, [0.5, 0.5]):
        raw = {"answers": {"d": {"type": "choice", "choice": "a", "probabilities": probs,
                                 "confidence": 1.0}}}
        with pytest.raises(TargetError, match=r"d\.probabilities missing"):
            map_answers(raw, q)


def test_unknown_declared_question_type_raises():
    q = {"w": {"type": "weird", "instructions": "x"}}
    raw = {"answers": {"w": {"type": "weird", "probabilities": {"a": 1.0}, "confidence": 1.0}}}
    with pytest.raises(TargetError, match="unknown question type 'weird'"):
        map_answers(raw, q)


def test_non_dict_answers_and_non_dict_entry_raise():
    q = {"d": {"type": "noul", "instructions": "x"}}
    with pytest.raises(TargetError, match="'answers' missing or not an object"):
        map_answers({"answers": []}, q)
    with pytest.raises(TargetError, match="no answer for question 'd'"):
        map_answers({"answers": {"d": 3}}, q)


def test_usage_validation_and_optional_fields():
    with pytest.raises(TargetError, match="input_tokens=True"):
        jev.map_usage({"usage": {"input_tokens": True}})
    with pytest.raises(TargetError, match="input_tokens='5'"):
        jev.map_usage({"usage": {"input_tokens": "5"}})
    assert jev.map_usage({"usage": {"input_tokens": 5}}) == (5, None, None)
    assert jev.map_usage({"usage": {"input_tokens": 5, "output_tokens": "x", "cost": "y"}}) == (
        5, None, None)
    assert jev.map_usage({"usage": {"input_tokens": 5, "cost": 3}}) == (5, None, 3.0)


# -------------------------------------------------------------- target ---
def test_blank_model_refused():
    with pytest.raises(TargetConfigError, match="needs a model id"):
        JevTarget("   ", api_key="k", base_url="https://x.example")


def test_from_env_names_missing_vars_without_values(monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "super-secret-value")
    monkeypatch.setenv("TYPESAFE_BASE_URL", "   ")
    with pytest.raises(TargetConfigError) as ei:
        JevTarget.from_env("jev-1.13")
    assert "TYPESAFE_BASE_URL" in str(ei.value)
    assert "super-secret-value" not in str(ei.value)


def test_custom_target_id_and_base_url_trailing_slash():
    t = JevTarget("jev-1.13", api_key="k", base_url="https://x.example/api/",
                  target_id="custom", transport=httpx2.MockTransport(lambda r: None))
    with t:
        assert t.target_id == "custom" and t.base_url == "https://x.example/api"


def test_connection_error_is_wrapped():
    def handler(request):
        raise httpx2.ConnectError("refused", request=request)

    t = JevTarget("jev-1.13", api_key="k", base_url="https://x.example/api",
                  timeout=2.0, transport=httpx2.MockTransport(handler))
    with t, pytest.raises(TargetError, match="jev connection error at /v1/systemone"):
        t.call("state", {"d": {"type": "noul", "instructions": "x"}})


def test_non_200_success_status_is_rejected():
    body = {"model": "typesafe/jev-1.13", "answers": {"d": {"type": "noul", "noul": 0.5}},
            "usage": {"input_tokens": 3}}
    t = JevTarget("jev-1.13", api_key="k", base_url="https://x.example/api",
                  transport=httpx2.MockTransport(
                      lambda r: httpx2.Response(201, content=json.dumps(body).encode())))
    with t, pytest.raises(TargetError, match="jev HTTP 201"):
        t.call("state", {"d": {"type": "noul", "instructions": "x"}})
