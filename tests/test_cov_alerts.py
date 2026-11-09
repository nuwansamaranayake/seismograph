"""Behavioural tests for app.alerts.send_alert with httpx faked."""
from __future__ import annotations

import httpx
import pytest

from app import alerts


class _Resp:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self):
        return self._payload


@pytest.fixture
def captured(monkeypatch):
    calls = []

    def fake_post(url, json=None, headers=None, timeout=None):
        calls.append({"url": url, "json": json, "headers": headers, "timeout": timeout})
        return _Resp(200, {"id": "msg_123"})

    monkeypatch.setattr(alerts.httpx, "post", fake_post)
    return calls


def test_missing_key_raises_without_calling_network(monkeypatch, captured):
    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    with pytest.raises(alerts.AlertError, match="RESEND_API_KEY is not set"):
        alerts.send_alert("s", "b")
    assert captured == []


def test_blank_key_counts_as_missing(monkeypatch, captured):
    monkeypatch.setenv("RESEND_API_KEY", "   ")
    with pytest.raises(alerts.AlertError, match="not set"):
        alerts.send_alert("s", "b")


def test_success_returns_id_and_sends_hardcoded_recipient(monkeypatch, captured):
    monkeypatch.setenv("RESEND_API_KEY", "key-abc")
    monkeypatch.delenv("SEISMO_ALERT_FROM", raising=False)
    assert alerts.send_alert("subj", "body text", timeout=5.0) == "msg_123"
    (call,) = captured
    assert call["url"] == alerts.RESEND_URL
    assert call["json"] == {
        "from": alerts.DEFAULT_FROM,
        "to": [alerts.RECIPIENT],
        "subject": "subj",
        "text": "body text",
    }
    assert call["headers"] == {"Authorization": "Bearer key-abc"}
    assert call["timeout"] == 5.0


def test_from_override_is_used_and_stripped(monkeypatch, captured):
    monkeypatch.setenv("RESEND_API_KEY", "k")
    monkeypatch.setenv("SEISMO_ALERT_FROM", "  alerts@example.test  ")
    alerts.send_alert("s", "b")
    assert captured[0]["json"]["from"] == "alerts@example.test"


def test_recipient_cannot_be_redirected_by_env(monkeypatch, captured):
    monkeypatch.setenv("RESEND_API_KEY", "k")
    monkeypatch.setenv("SEISMO_ALERT_TO", "evil@example.test")
    alerts.send_alert("s", "b")
    assert captured[0]["json"]["to"] == ["nuwan@aigniteconsulting.ai"]


def test_transport_failure_is_wrapped(monkeypatch):
    monkeypatch.setenv("RESEND_API_KEY", "k")

    def boom(*a, **k):
        raise httpx.ConnectError("no route")

    monkeypatch.setattr(alerts.httpx, "post", boom)
    with pytest.raises(alerts.AlertError, match="transport failure: no route") as ei:
        alerts.send_alert("s", "b")
    assert isinstance(ei.value.__cause__, httpx.ConnectError)


def test_http_rejection_includes_status_and_truncated_body(monkeypatch):
    monkeypatch.setenv("RESEND_API_KEY", "k")
    monkeypatch.setattr(
        alerts.httpx, "post", lambda *a, **k: _Resp(403, None, "x" * 1000)
    )
    with pytest.raises(alerts.AlertError, match="rejected the send: 403 x+") as ei:
        alerts.send_alert("s", "b")
    assert len(str(ei.value)) < 400


@pytest.mark.parametrize("payload", [{}, None, {"id": ""}])
def test_accepted_without_id_raises(monkeypatch, payload):
    monkeypatch.setenv("RESEND_API_KEY", "k")
    monkeypatch.setattr(alerts.httpx, "post", lambda *a, **k: _Resp(200, payload, "{}"))
    with pytest.raises(alerts.AlertError, match="no message id"):
        alerts.send_alert("s", "b")
