"""Adapter behaviour (docs/gates-spec.md g1_adapters_real).

The MCP transport is exercised against an in-process ASGI app that speaks the
real streamable-HTTP protocol — initialize, session header, tools/list, SSE
framing. That is a test double of the TRANSPORT, inside the dev path only; the
production path has no mock target and no fallback (Standard 3). What the tests
pin down is the behaviour the gate depends on: schemas come from the wire, bad
arguments never reach the server, and a failed call is stored as a failed run.
"""
from __future__ import annotations

import json

import httpx
import pytest
import sqlalchemy as sa

from app import db
from app.targets import (
    CallRecord,
    HttpTarget,
    McpTarget,
    TargetConfigError,
    TargetError,
    arguments_hash,
    extract,
    record_call,
    validate_against_schema,
)

# The schema the fake server SERVES. No copy of it exists in app/targets.py.
SERVED_SCHEMA = {
    "type": "object",
    "properties": {
        "date": {"type": "string"},
        "latitude": {"type": "number"},
        "house_system": {"type": "string", "enum": ["placidus", "whole_sign"]},
    },
    "required": ["date", "latitude"],
    "additionalProperties": False,
}


@pytest.fixture()
def session():
    engine = sa.create_engine("sqlite://", poolclass=sa.pool.StaticPool)
    db.metadata.create_all(engine)
    db.set_engine_for_tests(engine)
    return db.get_session()


# --------------------------------------------------------------------------- #
# a real-protocol MCP server, in process
# --------------------------------------------------------------------------- #
def make_mcp_server(record: list) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        record.append(request)
        message = json.loads(request.content)
        method = message.get("method")
        if method == "initialize":
            return httpx.Response(
                200,
                json={"jsonrpc": "2.0", "id": message["id"], "result": {"capabilities": {}}},
                headers={"Mcp-Session-Id": "sess-1"},
            )
        if method == "notifications/initialized":
            return httpx.Response(202)
        if method == "tools/list":
            body = {
                "jsonrpc": "2.0",
                "id": message["id"],
                "result": {
                    "tools": [
                        {"name": "compute_chart", "inputSchema": SERVED_SCHEMA},
                    ]
                },
            }
            # SSE framing — the transport must handle this encoding too.
            return httpx.Response(
                200,
                text=f"event: message\ndata: {json.dumps(body)}\n\n",
                headers={"content-type": "text/event-stream"},
            )
        if method == "tools/call":
            return httpx.Response(
                200,
                json={
                    "jsonrpc": "2.0",
                    "id": message["id"],
                    "result": {"content": [{"type": "text", "text": "lagna: Mesha"}]},
                },
            )
        return httpx.Response(400, json={"jsonrpc": "2.0", "error": {"message": "bad method"}})

    return httpx.MockTransport(handler)


@pytest.fixture()
def mcp(monkeypatch):
    requests: list[httpx.Request] = []
    transport = make_mcp_server(requests)
    real_post = httpx.post

    def routed_post(url, **kwargs):
        with httpx.Client(transport=transport) as c:
            return c.post(url, **kwargs)

    monkeypatch.setattr(httpx, "post", routed_post)
    target = McpTarget(target_id="calculator", url="https://example.test/mcp?token=cn-mcp-abc")
    assert real_post is not httpx.post
    return target, requests


# --------------------------------------------------------------------------- #
# arguments hash + json path
# --------------------------------------------------------------------------- #
def test_arguments_hash_is_key_order_independent():
    assert arguments_hash({"a": 1, "b": 2}) == arguments_hash({"b": 2, "a": 1})
    assert arguments_hash({"a": 1}) != arguments_hash({"a": 2})


def test_extract_walks_keys_and_indexes():
    payload = {"result": {"content": [{"text": "lagna: Mesha"}]}}
    assert extract(payload, "result.content[0].text") == "lagna: Mesha"


def test_extract_raises_rather_than_returning_none():
    with pytest.raises(TargetError):
        extract({"result": {}}, "result.missing")
    with pytest.raises(TargetError):
        extract({"result": {"content": []}}, "result.content[0]")


# --------------------------------------------------------------------------- #
# served-schema validation
# --------------------------------------------------------------------------- #
def test_validation_accepts_arguments_the_served_schema_allows():
    validate_against_schema({"date": "1985-04-12", "latitude": 6.9}, SERVED_SCHEMA)


@pytest.mark.parametrize(
    "arguments, reason",
    [
        ({"date": "1985-04-12"}, "missing required"),
        ({"date": "1985-04-12", "latitude": "6.9"}, "wrong type"),
        ({"date": "x", "latitude": 1, "colour": "red"}, "additionalProperties false"),
        ({"date": "x", "latitude": 1, "house_system": "koch"}, "outside enum"),
    ],
)
def test_validation_rejects_what_the_served_schema_forbids(arguments, reason):
    with pytest.raises(TargetError):
        validate_against_schema(arguments, SERVED_SCHEMA)


def test_integer_field_rejects_bool():
    with pytest.raises(TargetError):
        validate_against_schema({"n": True}, {"properties": {"n": {"type": "integer"}}})


# --------------------------------------------------------------------------- #
# mcp adapter
# --------------------------------------------------------------------------- #
def test_list_tools_reads_the_schema_off_the_wire(mcp):
    target, _ = mcp
    tools = target.list_tools()
    assert tools["compute_chart"]["inputSchema"] == SERVED_SCHEMA


def test_call_tool_initializes_once_and_carries_the_session_header(mcp):
    target, requests = mcp
    target.call_tool("compute_chart", {"date": "1985-04-12", "latitude": 6.9})
    target.call_tool("compute_chart", {"date": "1990-01-01", "latitude": 51.5})
    methods = [json.loads(r.content).get("method") for r in requests]
    assert methods.count("initialize") == 1
    assert methods.count("tools/list") == 1          # schema cached after the first read
    assert requests[-1].headers["mcp-session-id"] == "sess-1"


def test_successful_call_records_latency_and_response(mcp):
    target, _ = mcp
    rec = target.call_tool("compute_chart", {"date": "1985-04-12", "latitude": 6.9})
    assert rec.ok
    assert rec.adapter == "mcp" and rec.route == "compute_chart"
    assert rec.raw_response["content"][0]["text"] == "lagna: Mesha"
    assert rec.latency_ms >= 0 and rec.created_at is not None


def test_arguments_that_violate_the_served_schema_never_reach_the_server(mcp):
    target, requests = mcp
    rec = target.call_tool("compute_chart", {"date": "1985-04-12"})   # latitude missing
    assert not rec.ok and "required" in rec.error
    assert "tools/call" not in [json.loads(r.content).get("method") for r in requests]


def test_unknown_tool_is_a_failed_run_not_an_exception(mcp):
    target, _ = mcp
    rec = target.call_tool("not_a_tool", {})
    assert not rec.ok and "not served" in rec.error


# The suite runner calls target.call(body=..., json_path=...). Before this method existed,
# `seismo run --suite` with SEISMO_TARGET_ADAPTER=mcp raised AttributeError mid-run.
def test_the_suite_interface_maps_a_case_request_onto_a_tool_call(mcp):
    target, requests = mcp
    rec = target.call(body={"case_id": "syn-1", "tool": "compute_chart",
                            "date": "1985-04-12", "latitude": 6.9})
    assert rec.ok and rec.route == "compute_chart"
    sent = json.loads(requests[-1].content)["params"]
    assert sent == {"name": "compute_chart", "arguments": {"date": "1985-04-12", "latitude": 6.9}}


def test_the_suite_interface_applies_a_json_path_and_fails_loudly_when_it_misses(mcp):
    target, _ = mcp
    body = {"case_id": "syn-1", "tool": "compute_chart", "date": "1985-04-12", "latitude": 6.9}
    assert target.call(body=body, json_path="content[0].text").raw_response == "lagna: Mesha"
    missed = target.call(body=body, json_path="content[0].nope")
    assert not missed.ok and "no key 'nope'" in missed.error


def test_a_suite_case_without_a_tool_or_with_the_wrong_shape_is_a_failed_run(mcp):
    target, requests = mcp
    no_tool = target.call(body={"case_id": "syn-1", "date": "1985-04-12"})
    assert not no_tool.ok and "must name its tool" in no_tool.error and requests == []
    assert not target.call().ok
    # a case shaped for another tool: arguments are not reshaped, the served schema refuses
    wrong = target.call(body={"case_id": "syn-1", "tool": "compute_chart", "birth": {"date": "x"}},
                        json_path="content")
    assert not wrong.ok and "required" in wrong.error


def test_from_env_refuses_to_guess_a_url(monkeypatch):
    monkeypatch.delenv("CALCULATOR_MCP_URL", raising=False)
    with pytest.raises(TargetConfigError):
        McpTarget.from_env("calculator", "CALCULATOR_MCP_URL")


# --------------------------------------------------------------------------- #
# http adapter
# --------------------------------------------------------------------------- #
def test_http_target_reads_everything_from_env(monkeypatch):
    monkeypatch.setenv("SEISMO_TARGET_REPORTS_METHOD", "get")
    monkeypatch.setenv("SEISMO_TARGET_REPORTS_URL", "https://example.test/api/v1/health")
    monkeypatch.setenv("SEISMO_TARGET_REPORTS_HEADERS", '{"Authorization": "Bearer t"}')
    target = HttpTarget.from_env("reports")
    assert target.method == "GET"
    assert target.headers == {"Authorization": "Bearer t"}


def test_http_target_missing_url_is_a_config_error(monkeypatch):
    monkeypatch.setenv("SEISMO_TARGET_NOPE_METHOD", "GET")
    monkeypatch.delenv("SEISMO_TARGET_NOPE_URL", raising=False)
    with pytest.raises(TargetConfigError):
        HttpTarget.from_env("nope")


def test_http_call_extracts_a_json_path(monkeypatch):
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, json={"data": {"status": "ok"}})
    )
    monkeypatch.setattr(
        httpx,
        "request",
        lambda method, url, **kw: httpx.Client(transport=transport).request(method, url, **kw),
    )
    target = HttpTarget("reports", "GET", "https://example.test/x")
    rec = target.call(json_path="data.status")
    assert rec.ok and rec.raw_response == "ok"


def test_http_non_2xx_is_a_failed_run(monkeypatch):
    transport = httpx.MockTransport(lambda request: httpx.Response(502, text="bad gateway"))
    monkeypatch.setattr(
        httpx,
        "request",
        lambda method, url, **kw: httpx.Client(transport=transport).request(method, url, **kw),
    )
    rec = HttpTarget("reports", "GET", "https://example.test/x").call()
    assert not rec.ok and "502" in rec.error
    assert rec.raw_response is None


# --------------------------------------------------------------------------- #
# storage
# --------------------------------------------------------------------------- #
def test_record_call_stores_every_required_field(session):
    rec = CallRecord(
        target_id="calculator",
        adapter="mcp",
        route="compute_chart",
        arguments_hash=arguments_hash({"date": "1985-04-12"}),
        latency_ms=42,
        raw_response={"content": [{"text": "lagna: Mesha"}]},
    )
    row_id = record_call(session, rec)
    row = session.execute(
        sa.select(db.target_calls).where(db.target_calls.c.id == row_id)
    ).mappings().one()
    assert row["target_id"] == "calculator"
    assert row["adapter"] == "mcp"
    assert row["route"] == "compute_chart"
    assert row["arguments_hash"] == rec.arguments_hash
    assert row["raw_response"]["content"][0]["text"] == "lagna: Mesha"
    assert row["latency_ms"] == 42
    assert row["error"] is None
    assert row["created_at"] is not None


def test_a_failed_call_is_stored_as_a_failed_run(session):
    rec = CallRecord(
        target_id="calculator",
        adapter="http",
        route="GET https://example.test/x",
        arguments_hash=arguments_hash(None),
        latency_ms=7,
        error="HTTPStatusError: 502",
    )
    row_id = record_call(session, rec)
    row = session.execute(
        sa.select(db.target_calls).where(db.target_calls.c.id == row_id)
    ).mappings().one()
    assert row["error"].startswith("HTTPStatusError")
    assert row["raw_response"] is None
