"""Remaining branches of app.targets, with httpx.request / httpx.post faked."""
from __future__ import annotations

import json

import httpx
import pytest

from app import targets
from app.targets import (
    HttpTarget,
    McpTarget,
    TargetConfigError,
    TargetError,
    extract,
    validate_against_schema,
)


# ------------------------------------------------------------ extract ---
def test_extract_index_and_key_errors():
    payload = {"a": [{"b": 1}, {"b": 2}]}
    assert extract(payload, "a[1].b") == 2
    assert extract(payload, "a[-1].b") == 2
    with pytest.raises(TargetError, match="no index 5"):
        extract(payload, "a[5].b")
    with pytest.raises(TargetError, match="no index 0"):
        extract({"a": {}}, "a[0]")
    with pytest.raises(TargetError, match="no key 'zzz'"):
        extract(payload, "zzz")
    with pytest.raises(TargetError, match="no key 'b'"):
        extract(payload, "a.b")


# ---------------------------------------------------- schema validation ---
def test_schema_must_be_object():
    with pytest.raises(TargetError, match="served schema is not an object"):
        validate_against_schema({}, ["nope"])


def test_top_level_type_mismatch():
    with pytest.raises(TargetError, match="expected object, got list"):
        validate_against_schema([], {"type": "object"})


def test_required_additional_and_nested():
    schema = {
        "type": "object",
        "required": ["a"],
        "additionalProperties": False,
        "properties": {
            "a": {"type": "integer"},
            "n": {"type": "object", "required": ["z"], "properties": {"z": {"type": "string"}}},
            "free": "not-a-dict-spec",
            "multi": {"type": ["string", "null"]},
            "flag": {"type": "boolean"},
        },
    }
    validate_against_schema({"a": 1, "multi": None, "free": 3, "n": {"z": "x"}}, schema)
    with pytest.raises(TargetError, match="missing required property 'a'"):
        validate_against_schema({}, schema)
    with pytest.raises(TargetError, match="property 'q' not allowed"):
        validate_against_schema({"a": 1, "q": 1}, schema)
    with pytest.raises(TargetError, match=r"arguments\.n: missing required property 'z'"):
        validate_against_schema({"a": 1, "n": {}}, schema)
    with pytest.raises(TargetError, match=r"arguments\.n\.z: expected string, got int"):
        validate_against_schema({"a": 1, "n": {"z": 5}}, schema)
    with pytest.raises(TargetError, match=r"expected string\|null, got int"):
        validate_against_schema({"a": 1, "multi": 3}, schema)
    with pytest.raises(TargetError, match="expected integer, got boolean"):
        validate_against_schema({"a": True}, schema)
    # an integer field rejects a float
    with pytest.raises(TargetError, match="expected integer, got float"):
        validate_against_schema({"a": 1.5}, schema)


def test_unknown_schema_type_is_left_alone():
    validate_against_schema({"x": 1}, {"type": "weird", "properties": {"x": {"type": "alien"}}})


# ------------------------------------------------------------ HttpTarget ---
def _clear_env(monkeypatch, prefix):
    for suffix in ("METHOD", "URL", "HEADERS", "TIMEOUT"):
        monkeypatch.delenv(f"{prefix}_{suffix}", raising=False)


def test_from_env_reads_everything(monkeypatch):
    p = "SEISMO_TARGET_MY_SVC"
    _clear_env(monkeypatch, p)
    monkeypatch.setenv(f"{p}_METHOD", "post")
    monkeypatch.setenv(f"{p}_URL", "https://example.test/x?k=1")
    monkeypatch.setenv(f"{p}_HEADERS", json.dumps({"X-Key": 7}))
    monkeypatch.setenv(f"{p}_TIMEOUT", "2.5")
    t = HttpTarget.from_env("my-svc")
    assert (t.method, t.url, t.headers, t.timeout) == (
        "POST", "https://example.test/x?k=1", {"X-Key": "7"}, 2.5)


def test_from_env_defaults_and_errors(monkeypatch):
    p = "SEISMO_TARGET_ZED"
    _clear_env(monkeypatch, p)
    with pytest.raises(TargetConfigError, match="ZED_METHOD is not set"):
        HttpTarget.from_env("zed")
    monkeypatch.setenv(f"{p}_METHOD", "get")
    monkeypatch.setenv(f"{p}_URL", "https://example.test/")
    t = HttpTarget.from_env("zed")
    assert t.headers == {} and t.timeout == 30.0
    monkeypatch.setenv(f"{p}_HEADERS", "{bad")
    with pytest.raises(TargetConfigError, match="not valid JSON"):
        HttpTarget.from_env("zed")
    monkeypatch.setenv(f"{p}_HEADERS", "[1]")
    with pytest.raises(TargetConfigError, match="must be a JSON object"):
        HttpTarget.from_env("zed")


def test_http_call_success_with_json_path_and_request_shape(monkeypatch):
    seen = {}

    def fake_request(method, url, json=None, headers=None, timeout=None, follow_redirects=None):
        seen.update(method=method, url=url, json=json, headers=headers,
                    timeout=timeout, follow=follow_redirects)
        return httpx.Response(200, json={"data": {"v": 3}},
                              request=httpx.Request(method, url))

    monkeypatch.setattr(targets.httpx, "request", fake_request)
    t = HttpTarget("tid", "POST", "https://example.test/p?secret=1", {"X": "y"}, 4.0)
    rec = t.call({"q": 1}, json_path="data")
    assert rec.error is None and rec.raw_response == {"v": 3}
    assert rec.route == "POST https://example.test/p"   # query string (credential) dropped
    assert rec.adapter == "http" and rec.ok
    assert seen["headers"] == {"Accept": "application/json", "X": "y"}
    assert seen["json"] == {"q": 1} and seen["timeout"] == 4.0 and seen["follow"] is True


def test_http_call_without_json_path_returns_whole_payload(monkeypatch):
    monkeypatch.setattr(targets.httpx, "request", lambda m, u, **k: httpx.Response(
        200, json=[1, 2], request=httpx.Request(m, u)))
    rec = HttpTarget("t", "GET", "https://example.test/").call()
    assert rec.raw_response == [1, 2]


@pytest.mark.parametrize("make,needle", [
    (lambda m, u: httpx.Response(500, request=httpx.Request(m, u)), "HTTPStatusError"),
    (lambda m, u: httpx.Response(200, content=b"<html>", request=httpx.Request(m, u)),
     "JSONDecodeError"),
])
def test_http_call_failures_become_error_records(monkeypatch, make, needle):
    monkeypatch.setattr(targets.httpx, "request", lambda m, u, **k: make(m, u))
    rec = HttpTarget("t", "GET", "https://example.test/").call({"a": 1})
    assert rec.raw_response is None and needle in rec.error and not rec.ok


def test_http_call_bad_json_path_and_transport_error(monkeypatch):
    monkeypatch.setattr(targets.httpx, "request", lambda m, u, **k: httpx.Response(
        200, json={"a": 1}, request=httpx.Request(m, u)))
    rec = HttpTarget("t", "GET", "https://example.test/").call(json_path="missing")
    assert rec.error.startswith("TargetError:") and "no key 'missing'" in rec.error

    def boom(*a, **k):
        raise httpx.ConnectError("refused")

    monkeypatch.setattr(targets.httpx, "request", boom)
    rec = HttpTarget("t", "GET", "https://example.test/").call()
    assert rec.error == "ConnectError: refused"


# -------------------------------------------------------------- McpTarget ---
class Server:
    """Scripted httpx.post replacement. `replies` maps JSON-RPC method -> response factory."""

    def __init__(self, replies, session="sess-1"):
        self.replies = replies
        self.session = session
        self.sent = []

    def __call__(self, url, json=None, headers=None, timeout=None):
        self.sent.append((json, dict(headers)))
        method = json.get("method")
        make = self.replies[method]
        resp = make(json)
        if self.session and method == "initialize":
            resp.headers["mcp-session-id"] = self.session
        return resp


def _ok(result):
    return lambda req: httpx.Response(
        200, json={"jsonrpc": "2.0", "id": req.get("id"), "result": result},
        request=httpx.Request("POST", "https://m.test/"))


def _resp(status, **kw):
    return httpx.Response(status, request=httpx.Request("POST", "https://m.test/"), **kw)


TOOLS = {"tools": [{"name": "t1", "inputSchema": {
    "type": "object", "required": ["x"], "properties": {"x": {"type": "integer"}}}}]}


def _server(call_reply, tools=TOOLS, session="sess-1"):
    return Server({
        "initialize": _ok({}),
        "notifications/initialized": lambda r: _resp(202),
        "tools/list": _ok(tools),
        "tools/call": call_reply,
    }, session=session)


def test_from_env(monkeypatch):
    monkeypatch.setenv("MY_MCP_URL", "https://m.test/mcp?token=a-mcp-1")
    t = McpTarget.from_env("mcp1", "MY_MCP_URL")
    assert (t.target_id, t.url) == ("mcp1", "https://m.test/mcp?token=a-mcp-1")
    monkeypatch.delenv("MY_MCP_URL")
    with pytest.raises(TargetConfigError, match="MY_MCP_URL is not set"):
        McpTarget.from_env("mcp1", "MY_MCP_URL")


def test_call_tool_happy_path_sends_session_and_caches_tools(monkeypatch):
    srv = _server(_ok({"content": [{"text": "hi"}]}))
    monkeypatch.setattr(targets.httpx, "post", srv)
    t = McpTarget("m", "https://m.test/")
    r1 = t.call_tool("t1", {"x": 1})
    r2 = t.call_tool("t1", {"x": 2})
    assert r1.raw_response == {"content": [{"text": "hi"}]} and r1.error is None
    assert r2.error is None
    methods = [m["method"] for m, _ in srv.sent]
    assert methods == ["initialize", "notifications/initialized", "tools/list",
                       "tools/call", "tools/call"]               # one handshake only
    assert "Mcp-Session-Id" not in srv.sent[0][1]
    assert srv.sent[3][1]["Mcp-Session-Id"] == "sess-1"
    assert srv.sent[3][0]["params"] == {"name": "t1", "arguments": {"x": 1}}
    assert t.list_tools(refresh=True).keys() == {"t1"}          # refresh re-reads


def test_server_without_session_id_still_initializes_once(monkeypatch):
    srv = _server(_ok({}), session=None)
    monkeypatch.setattr(targets.httpx, "post", srv)
    t = McpTarget("m", "https://m.test/")
    t.call_tool("t1", {"x": 1})
    t.call_tool("t1", {"x": 1})
    assert [m["method"] for m, _ in srv.sent].count("initialize") == 1
    assert "Mcp-Session-Id" not in srv.sent[-1][1]


def test_unknown_tool_and_bad_arguments_never_reach_server(monkeypatch):
    srv = _server(_ok({}))
    monkeypatch.setattr(targets.httpx, "post", srv)
    t = McpTarget("m", "https://m.test/")
    bad_tool = t.call_tool("nope", {})
    assert "tool 'nope' not served (have: ['t1'])" in bad_tool.error
    bad_args = t.call_tool("t1", {})
    assert "missing required property 'x'" in bad_args.error
    assert all(m["method"] != "tools/call" for m, _ in srv.sent)


def test_tool_error_and_no_result(monkeypatch):
    srv = _server(_ok({"isError": True}))
    monkeypatch.setattr(targets.httpx, "post", srv)
    rec = McpTarget("m", "https://m.test/").call_tool("t1", {"x": 1})
    assert "reported isError" in rec.error
    srv = _server(lambda r: _resp(202))
    monkeypatch.setattr(targets.httpx, "post", srv)
    rec = McpTarget("m", "https://m.test/").call_tool("t1", {"x": 1})
    assert "tools/call returned no result" in rec.error


def test_empty_tool_list_is_an_error(monkeypatch):
    monkeypatch.setattr(targets.httpx, "post", _server(_ok({}), tools={"tools": []}))
    with pytest.raises(TargetError, match="tools/list returned no tools"):
        McpTarget("m", "https://m.test/").list_tools()


def test_401_is_a_clear_error(monkeypatch):
    srv = Server({"initialize": lambda r: _resp(401)})
    monkeypatch.setattr(targets.httpx, "post", srv)
    with pytest.raises(TargetError, match="401 from MCP endpoint"):
        McpTarget("m", "https://m.test/").list_tools()


def test_json_rpc_error_message_raises(monkeypatch):
    srv = Server({"initialize": lambda r: _resp(200, json={"error": {"code": -1}})})
    monkeypatch.setattr(targets.httpx, "post", srv)
    with pytest.raises(TargetError, match="MCP error"):
        McpTarget("m", "https://m.test/").list_tools()


def test_sse_encoded_replies(monkeypatch):
    def sse(result):
        def make(req):
            body = "event: message\ndata: " + json.dumps({"result": result}) + "\n\n"
            return _resp(200, content=body.encode(),
                         headers={"content-type": "text/event-stream"})
        return make

    srv = Server({
        "initialize": sse({}),
        "notifications/initialized": lambda r: _resp(202),
        "tools/list": sse(TOOLS),
        "tools/call": sse({"ok": True}),
    })
    monkeypatch.setattr(targets.httpx, "post", srv)
    rec = McpTarget("m", "https://m.test/").call_tool("t1", {"x": 1})
    assert rec.raw_response == {"ok": True}


def test_sse_without_data_frame_yields_no_result(monkeypatch):
    srv = _server(lambda r: _resp(200, content=b": keepalive\n\n",
                                  headers={"content-type": "text/event-stream"}))
    monkeypatch.setattr(targets.httpx, "post", srv)
    rec = McpTarget("m", "https://m.test/").call_tool("t1", {"x": 1})
    assert "returned no result" in rec.error


def test_first_sse_data_helper():
    assert targets._first_sse_data("event: x\ndata:{\"a\": 1}\n") == {"a": 1}
    assert targets._first_sse_data("no frames") is None
