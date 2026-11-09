"""Jev adapter behaviour.

The TypeSafe SDK speaks HTTP through httpx2; these tests hand it a MockTransport
that serves a response body shaped exactly like the live OpenRouter reply the
2026-09-21 smoke test recorded (a local smoke test). That is a
double of the TRANSPORT inside the test process only: the adapter has no mock
path and no fallback (Standard 3). What is pinned down: the mapping onto the
run record, that a malformed reply raises instead of defaulting, and that a
missing credential refuses to build a target at all.
"""
from __future__ import annotations

import json

import httpx2
import pytest

from app.jev import JevCallRecord, JevTarget, map_answers
from app.targets import TargetConfigError, TargetError

QUESTIONS = {
    "refund_requested": {"type": "noul", "instructions": "Is the customer asking for money back?"},
    "department": {
        "type": "choice",
        "instructions": "Which team should handle this ticket?",
        "criteria": {"billing": "Charges", "technical": "Bugs", "sales": "Pricing", "account": "Login"},
    },
    "frustration": {
        "type": "score",
        "instructions": "How frustrated is the customer?",
        "criteria": ["Calm", "Annoyed", "Frustrated", "Very angry"],
    },
}

# Shape recorded from the live call on 2026-09-21 (values rounded).
LIVE_SHAPED_BODY = {
    "id": "gen-example",
    "model": "typesafe/jev-1.13-20260917",
    "provider": "TypeSafe",
    "answers": {
        "refund_requested": {"type": "noul", "noul": 0.97},
        "department": {
            "type": "choice", "choice": "billing",
            "probabilities": {"billing": 0.97, "technical": 0.02, "sales": 0.01, "account": 0.0},
            "confidence": 0.95,
        },
        "frustration": {
            "type": "score", "score": 2.0,
            "legend": {"0": "Calm", "1": "Annoyed", "2": "Frustrated", "3": "Very angry"},
            "probabilities": {"0": 0.0, "1": 0.0, "2": 1.0, "3": 0.0},
            "confidence": 1.0,
        },
    },
    "usage": {"input_tokens": 558, "output_tokens": 78, "cost": 2.3436e-05},
}


def _target(body, status=200, monkeypatch=None):
    seen = {}

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content)
        seen["auth"] = request.headers.get("authorization", "")
        return httpx2.Response(status, json=body)

    if monkeypatch is not None:
        monkeypatch.setenv("TYPESAFE_API_KEY", "test-key-not-real")
        monkeypatch.setenv("TYPESAFE_BASE_URL", "https://openrouter.example/api")
        t = JevTarget.from_env("jev-1.13", transport=httpx2.MockTransport(handler))
    else:
        t = JevTarget("jev-1.13", api_key="test-key-not-real", base_url="https://openrouter.example/api",
                      transport=httpx2.MockTransport(handler))
    return t, seen


def test_live_response_maps_onto_run_record(monkeypatch):
    target, seen = _target(LIVE_SHAPED_BODY, monkeypatch=monkeypatch)
    with target:
        rec = target.call("I was charged twice.", QUESTIONS, probe_id="p1", run_index=2)

    # Request shape: model, state, questions and nothing invented (TypeSafe API doc).
    assert seen["url"] == "https://openrouter.example/api/v1/systemone"
    assert set(seen["body"]) == {"model", "state", "questions"}
    assert seen["body"]["model"] == "jev-1.13"
    assert seen["auth"].startswith("Bearer ")

    # Seismograph's run record fields, plus the Jev fields.
    assert isinstance(rec, JevCallRecord)
    assert rec.adapter == "jev" and rec.route == "/v1/systemone" and rec.error is None
    assert rec.target_id == "jev:jev-1.13" and rec.probe_id == "p1" and rec.run_index == 2
    assert rec.latency_ms >= 0 and len(rec.arguments_hash) > 8
    assert set(rec.answers) == {"refund_requested", "department", "frustration"}
    assert rec.answers["department"].answer == "billing"
    assert rec.answers["department"].probabilities == {"billing": 0.97, "technical": 0.02, "sales": 0.01, "account": 0.0}
    assert rec.answers["refund_requested"].answer == pytest.approx(0.97)
    assert rec.answers["refund_requested"].probabilities == {"true": pytest.approx(0.97), "false": pytest.approx(0.03)}
    assert rec.answers["frustration"].answer == 2.0
    assert rec.usage_cost == pytest.approx(2.3436e-05)
    assert rec.input_tokens == 558 and rec.output_tokens == 78
    assert rec.model == "typesafe/jev-1.13-20260917"

    # Round trip through the JSONL run-record form.
    again = JevCallRecord.from_json(json.loads(json.dumps(rec.to_json())))
    assert again.answers["department"].probabilities == rec.answers["department"].probabilities
    assert again.usage_cost == rec.usage_cost


@pytest.mark.parametrize("mutate, fragment", [
    (lambda b: b.pop("answers"), "'answers' missing"),
    (lambda b: b["answers"].pop("department"), "no answer for question 'department'"),
    (lambda b: b["answers"]["department"].__setitem__("choice", "legal"), "not in declared options"),
    (lambda b: b["answers"]["department"].__setitem__("probabilities", {"billing": 0.6, "technical": 0.6, "sales": 0.0, "account": 0.0}), "sum to"),
    (lambda b: b["answers"]["department"]["probabilities"].pop("account"), "differ from declared options"),
    (lambda b: b["answers"]["refund_requested"].__setitem__("noul", 1.4), "outside [0, 1]"),
    # The next three are rejected by the SDK's own response schema before the adapter's
    # mapper runs; the adapter re-raises them as malformed (see the map_* tests below for
    # the adapter's own checks on the same defects).
    (lambda b: b["answers"]["refund_requested"].__setitem__("type", "choice"), "malformed response"),
    (lambda b: b["answers"]["frustration"].__setitem__("score", "high"), "malformed response"),
    (lambda b: b.pop("usage"), "malformed response"),
    (lambda b: b["usage"].__setitem__("input_tokens", 0), "input_tokens=0"),
])
def test_malformed_response_raises_never_defaults(monkeypatch, mutate, fragment):
    body = json.loads(json.dumps(LIVE_SHAPED_BODY))
    mutate(body)
    target, _ = _target(body, monkeypatch=monkeypatch)
    with target, pytest.raises(TargetError) as excinfo:
        target.call("state", QUESTIONS)
    assert fragment in str(excinfo.value)


def test_map_answers_rejects_non_object_body():
    with pytest.raises(TargetError):
        map_answers(["not", "an", "object"], QUESTIONS)


@pytest.mark.parametrize("mutate, fragment", [
    (lambda a: a["refund_requested"].__setitem__("type", "choice"), "answered as 'choice'"),
    (lambda a: a["frustration"].__setitem__("score", "high"), "expected a number"),
    (lambda a: a["frustration"].__setitem__("probabilities", {"0": 1.0, "1": 0.0}), "differ from declared levels"),
])
def test_map_answers_own_checks(mutate, fragment):
    answers = json.loads(json.dumps(LIVE_SHAPED_BODY["answers"]))
    mutate(answers)
    with pytest.raises(TargetError, match=fragment):
        map_answers({"answers": answers}, QUESTIONS)


def test_probability_tolerance_scales_with_rounded_options():
    """57 rounded two-decimal probabilities may legitimately sum to 0.99; four may not sum to 0.97."""
    from app.jev import prob_tolerance

    assert prob_tolerance(4) == pytest.approx(0.02)
    assert prob_tolerance(57) == pytest.approx(0.285)
    n = 57
    options = {f"opt{i}": None for i in range(n)}
    probs = {f"opt{i}": 0.01 for i in range(n - 1)}
    probs["opt56"] = 0.43  # 56 x 0.01 + 0.43 = 0.99
    q = {"skill": {"type": "choice", "instructions": "x", "criteria": options}}
    raw = {"answers": {"skill": {"type": "choice", "choice": "opt56", "probabilities": probs, "confidence": 0.4}}}
    assert map_answers(raw, q)["skill"].answer == "opt56"

    q4 = {"d": QUESTIONS["department"]}
    bad = {"answers": {"d": {"type": "choice", "choice": "billing",
                             "probabilities": {"billing": 0.94, "technical": 0.02, "sales": 0.01, "account": 0.0},
                             "confidence": 0.9}}}
    with pytest.raises(TargetError, match="sum to 0.9700"):
        map_answers(bad, q4)


def test_map_usage_own_checks():
    from app.jev import map_usage

    with pytest.raises(TargetError, match="'usage' missing"):
        map_usage({"answers": {}})
    assert map_usage({"usage": {"input_tokens": 12, "output_tokens": 3, "cost": 1e-6}}) == (12, 3, 1e-6)


def test_http_error_carries_status_and_body(monkeypatch):
    target, _ = _target({"error": {"message": "User not found."}}, status=401, monkeypatch=monkeypatch)
    with target, pytest.raises(TargetError) as excinfo:
        target.call("state", QUESTIONS)
    msg = str(excinfo.value)
    assert "401" in msg and "User not found" in msg


def test_non_jev_model_in_response_raises(monkeypatch):
    body = json.loads(json.dumps(LIVE_SHAPED_BODY))
    body["model"] = "openai/gpt-4o-mini"
    target, _ = _target(body, monkeypatch=monkeypatch)
    with target, pytest.raises(TargetError, match="not a Jev model"):
        target.call("state", QUESTIONS)


@pytest.mark.parametrize("missing", ["TYPESAFE_API_KEY", "TYPESAFE_BASE_URL"])
def test_refuses_to_run_without_credentials(monkeypatch, missing):
    monkeypatch.setenv("TYPESAFE_API_KEY", "test-key-not-real")
    monkeypatch.setenv("TYPESAFE_BASE_URL", "https://openrouter.example/api")
    monkeypatch.delenv(missing)
    with pytest.raises(TargetConfigError) as excinfo:
        JevTarget.from_env("jev-1.13")
    assert missing in str(excinfo.value)
    assert "test-key-not-real" not in str(excinfo.value)


def test_refuses_blank_credentials(monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "   ")
    monkeypatch.setenv("TYPESAFE_BASE_URL", "https://openrouter.example/api")
    with pytest.raises(TargetConfigError, match="TYPESAFE_API_KEY"):
        JevTarget.from_env("jev-1.13")
