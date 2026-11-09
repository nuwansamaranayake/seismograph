"""Outbound alerts for a failed or incomplete suite run.

One recipient, hardcoded: alert mail goes to nuwan@aigniteconsulting.ai ONLY. It is a constant rather than an
env var so a misconfigured environment cannot redirect eval alerts to a third
party.

The From line is `onboarding@resend.dev` by default. Set SEISMO_ALERT_FROM to send from
a verified domain.

A send that Resend does not accept raises. An eval that silently fails to alert
is worse than one that stops.
"""
from __future__ import annotations

import os

import httpx

RECIPIENT = "nuwan@aigniteconsulting.ai"
DEFAULT_FROM = "onboarding@resend.dev"
RESEND_URL = "https://api.resend.com/emails"


class AlertError(RuntimeError):
    """The alert could not be sent. Never swallowed."""


def send_alert(subject: str, body: str, timeout: float = 20.0) -> str:
    """Send one alert and return the Resend message id.

    Raises AlertError when the key is missing or Resend rejects the send.
    """
    api_key = os.environ.get("RESEND_API_KEY", "").strip()
    if not api_key:
        raise AlertError("RESEND_API_KEY is not set; cannot alert")

    payload = {
        "from": os.environ.get("SEISMO_ALERT_FROM", "").strip() or DEFAULT_FROM,
        "to": [RECIPIENT],
        "subject": subject,
        "text": body,
    }
    try:
        response = httpx.post(
            RESEND_URL,
            json=payload,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=timeout,
        )
    except httpx.HTTPError as exc:
        raise AlertError(f"resend transport failure: {exc}") from exc

    if response.status_code >= 300:
        raise AlertError(f"resend rejected the send: {response.status_code} {response.text[:300]}")
    message_id = (response.json() or {}).get("id")
    if not message_id:
        raise AlertError(f"resend accepted but returned no message id: {response.text[:300]}")
    return message_id
