"""Drive both adapters against REAL endpoints and store what came back.

Runs inside the check image, on the compose network, with DATABASE_URL pointing
at the stack's Postgres. `scripts/gates.py g1_adapters_real` invokes it and reads
the JSON summary off the last line of stdout.

Nothing here is mocked. The http target is the live production Seismograph
report API; the mcp target is whatever CALCULATOR_MCP_URL serves. A target whose
configuration is absent is reported as blocked — never substituted, never
skipped quietly (Standard 3).
"""
from __future__ import annotations

import json
import os
import sys

import sqlalchemy as sa

from app import db
from app.targets import HttpTarget, McpTarget, TargetConfigError, record_call

SUMMARY_PREFIX = "SUMMARY_JSON "


def _rows_for(session, adapter: str) -> int:
    return session.execute(
        sa.select(sa.func.count())
        .select_from(db.target_calls)
        .where(db.target_calls.c.adapter == adapter, db.target_calls.c.error.is_(None))
    ).scalar_one()


def run_http(session) -> dict:
    """Call the live report API through the http adapter, with JSON-path extraction."""
    try:
        target = HttpTarget.from_env("reports")
    except TargetConfigError as exc:
        return {"ok": False, "blocked": str(exc)}

    rec = target.call(json_path=os.environ.get("SEISMO_TARGET_REPORTS_JSON_PATH") or None)
    row_id = record_call(session, rec)
    return {
        "ok": rec.ok and bool(rec.raw_response),
        "row_id": row_id,
        "route": rec.route,
        "latency_ms": rec.latency_ms,
        "error": rec.error,
        "response_preview": json.dumps(rec.raw_response, default=str)[:200],
    }


def run_mcp(session) -> dict:
    """Read tools/list off the wire, then call a served tool with served-schema
    validated arguments. The tool and its arguments come from env so no schema is
    ever hardcoded here."""
    try:
        target = McpTarget.from_env("calculator", "CALCULATOR_MCP_URL")
        tool = os.environ["SEISMO_CALCULATOR_TOOL"]
        arguments = json.loads(os.environ["SEISMO_CALCULATOR_ARGS"])
    except (TargetConfigError, KeyError) as exc:
        return {"ok": False, "blocked": f"missing target configuration: {exc}"}

    try:
        served = sorted(target.list_tools())
    except Exception as exc:  # noqa: BLE001 - reported, not raised
        return {"ok": False, "error": f"tools/list failed: {type(exc).__name__}: {exc}"}

    rec = target.call_tool(tool, arguments)
    row_id = record_call(session, rec)
    return {
        "ok": rec.ok and bool(rec.raw_response),
        "row_id": row_id,
        "route": rec.route,
        "served_tools": served,
        "latency_ms": rec.latency_ms,
        "error": rec.error,
        "response_preview": json.dumps(rec.raw_response, default=str)[:200],
    }


def main() -> int:
    session = db.get_session()
    summary = {"http": run_http(session), "mcp": run_mcp(session)}
    summary["rows"] = {
        "http": _rows_for(session, "http"),
        "mcp": _rows_for(session, "mcp"),
    }
    for adapter in ("http", "mcp"):
        result = summary[adapter]
        state = "OK" if result["ok"] else ("BLOCKED" if result.get("blocked") else "FAILED")
        print(f"{adapter}: {state} {result.get('error') or result.get('blocked') or ''}")
    print(SUMMARY_PREFIX + json.dumps(summary, default=str))
    return 0 if summary["http"]["ok"] and summary["mcp"]["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
