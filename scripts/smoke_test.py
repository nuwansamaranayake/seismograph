"""Smoke: real business endpoints with real processing, against a running instance.

Flow: health -> dev fixture -> register the demo contract (idempotent: 201 or 409) ->
execute a run against the in-process stable SUT -> fetch the report and assert schema-valid,
non-empty results including a gate decision. Requires the database to be up (Standard 2:
a health check alone is not a smoke test).
"""
import os
import sys
from pathlib import Path

import httpx

BASE = f"http://{os.getenv('API_HOST', '127.0.0.1')}:{os.getenv('API_PORT', '8000')}"
TOKEN = os.getenv("SMOKE_TEST_TOKEN", "")
HEADERS = {"Authorization": f"Bearer {TOKEN}"}
CONTRACT = Path(__file__).resolve().parent.parent / "data" / "synthetic" / "contract.yaml"


def get(path: str):
    r = httpx.get(BASE + path, headers=HEADERS, timeout=10)
    r.raise_for_status()
    body = r.json()
    assert body, f"{path} returned an empty body"
    return body


def main():
    get("/health")
    data = get("/api/v1/demo")
    assert data.get("items"), "demo endpoint returned no items"

    r = httpx.post(BASE + "/api/v1/contracts", headers=HEADERS,
                   json={"yaml": CONTRACT.read_text(encoding="utf-8")}, timeout=15)
    assert r.status_code in (201, 409), f"contract register: {r.status_code} {r.text[:200]}"

    r = httpx.post(BASE + "/api/v1/runs", headers=HEADERS,
                   json={"contract": "refund-decision-stability", "sut": "stable"},
                   timeout=60)
    r.raise_for_status()
    run = r.json()
    assert run.get("cells", 0) > 0, "run executed no plan cells"
    assert run.get("gate") in ("pass", "block"), "run returned no gate decision"

    report = get("/api/v1/reports/refund-decision-stability")
    assert report.get("runs", 0) >= 1, "report shows no runs"
    assert report.get("metrics"), "report has no consistency metrics"
    assert report["latest_gate"]["decision"] in ("pass", "block")
    print("SMOKE OK")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"SMOKE FAILED: {e}", file=sys.stderr)
        sys.exit(1)
