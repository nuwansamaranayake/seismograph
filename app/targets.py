"""Target adapters — how Seismograph calls the AI systems it evaluates.

Two adapters, no more (docs/gates-spec.md, g1_adapters_real):

- `McpTarget`  streamable-HTTP MCP client. The URL, credential included, comes from
  the environment. `tools/list` is read at RUN TIME
  and arguments are validated against the SERVED schema. No tool schema is ever
  hardcoded here — if the server changes a tool, this client follows it.
- `HttpTarget` method, URL and headers from env; JSON body; JSON-path extraction.

Every call returns a `CallRecord` carrying target id, route, arguments hash, raw
response, latency, timestamp and error, and `record_call` persists it. A failed
call is a failed run: the record is stored with `error` set and `ok` False. There
is no silent fallback and no mock target (Standard 3) — a missing env var raises
`TargetConfigError` rather than inventing a default.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import httpx

from .db import target_calls


class TargetError(RuntimeError):
    """A target call failed, or a response could not be used as promised."""


class TargetConfigError(TargetError):
    """A required target env var is missing. Never defaulted, never guessed."""


# --------------------------------------------------------------------------- #
# call records
# --------------------------------------------------------------------------- #
def arguments_hash(arguments: Any) -> str:
    """SHA-256 over a canonical JSON rendering, so equal arguments hash equally
    regardless of key order or incidental whitespace."""
    canonical = json.dumps(arguments, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


@dataclass(frozen=True)
class CallRecord:
    target_id: str
    adapter: str
    route: str
    arguments_hash: str
    latency_ms: int
    raw_response: Any = None
    error: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @property
    def ok(self) -> bool:
        return self.error is None


def record_call(session, rec: CallRecord) -> int:
    """Persist one call record and return its row id. Callers store failures too —
    that is the point: a failed call has to be visible as a failed run."""
    result = session.execute(
        target_calls.insert().values(
            target_id=rec.target_id,
            adapter=rec.adapter,
            route=rec.route,
            arguments_hash=rec.arguments_hash,
            raw_response=rec.raw_response,
            latency_ms=rec.latency_ms,
            error=rec.error,
            created_at=rec.created_at,
        )
    )
    session.commit()
    return result.inserted_primary_key[0]


def _env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise TargetConfigError(f"{name} is not set")
    return value


# --------------------------------------------------------------------------- #
# JSON-path extraction
# --------------------------------------------------------------------------- #
def extract(payload: Any, path: str) -> Any:
    """Read a dotted path out of a decoded JSON payload: `a.b[0].c`.

    Raises TargetError when the path does not resolve. An eval that silently
    reads None where it expected a value is worse than one that stops.
    """
    current = payload
    for token in [t for t in path.replace("[", ".[").split(".") if t]:
        if token.startswith("[") and token.endswith("]"):
            index = int(token[1:-1])
            if not isinstance(current, list) or not -len(current) <= index < len(current):
                raise TargetError(f"json path {path!r}: no index {index} at {token}")
            current = current[index]
        else:
            if not isinstance(current, dict) or token not in current:
                raise TargetError(f"json path {path!r}: no key {token!r}")
            current = current[token]
    return current


# --------------------------------------------------------------------------- #
# served-schema validation (MCP)
# --------------------------------------------------------------------------- #
_JSON_TYPES: dict[str, Any] = {
    "object": dict,
    "array": list,
    "string": str,
    "number": (int, float),
    "integer": int,
    "boolean": bool,
    "null": type(None),
}


def validate_against_schema(arguments: dict, schema: dict, where: str = "arguments") -> None:
    """Validate `arguments` against the schema the server served for this tool.

    Deliberately small: required keys, declared types, enums, additionalProperties
    and one level of nested objects — the parts an MCP inputSchema actually uses.
    Anything it cannot interpret it leaves alone rather than inventing a rule.
    """
    if not isinstance(schema, dict):
        raise TargetError(f"{where}: served schema is not an object")

    expected = schema.get("type")
    if expected and expected in _JSON_TYPES and not isinstance(arguments, _JSON_TYPES[expected]):
        raise TargetError(f"{where}: expected {expected}, got {type(arguments).__name__}")

    properties = schema.get("properties") or {}
    for key in schema.get("required") or []:
        if key not in arguments:
            raise TargetError(f"{where}: missing required property {key!r} (served schema)")

    if schema.get("additionalProperties") is False:
        for key in arguments:
            if key not in properties:
                raise TargetError(f"{where}: property {key!r} not allowed by served schema")

    for key, value in arguments.items():
        spec = properties.get(key)
        if not isinstance(spec, dict):
            continue
        declared = spec.get("type")
        types = declared if isinstance(declared, list) else [declared] if declared else []
        known = [_JSON_TYPES[t] for t in types if t in _JSON_TYPES]
        if known and not isinstance(value, tuple(known)):
            raise TargetError(
                f"{where}.{key}: expected {'|'.join(types)}, got {type(value).__name__}"
            )
        # bool is an int subclass in Python; an integer field must not accept True.
        if "integer" in types and "boolean" not in types and isinstance(value, bool):
            raise TargetError(f"{where}.{key}: expected integer, got boolean")
        if "enum" in spec and value not in spec["enum"]:
            raise TargetError(f"{where}.{key}: {value!r} not in served enum {spec['enum']}")
        if spec.get("type") == "object" and isinstance(value, dict):
            validate_against_schema(value, spec, where=f"{where}.{key}")


# --------------------------------------------------------------------------- #
# http adapter
# --------------------------------------------------------------------------- #
@dataclass
class HttpTarget:
    """A plain JSON-over-HTTP target. Everything comes from env, nothing is guessed."""

    target_id: str
    method: str
    url: str
    headers: dict[str, str] = field(default_factory=dict)
    timeout: float = 30.0

    @classmethod
    def from_env(cls, target_id: str) -> HttpTarget:
        """Read SEISMO_TARGET_<ID>_{METHOD,URL,HEADERS,TIMEOUT}.

        HEADERS is a JSON object. URL and METHOD are required; a missing one is a
        configuration failure, not a default.
        """
        prefix = f"SEISMO_TARGET_{target_id.upper().replace('-', '_')}"
        raw_headers = os.environ.get(f"{prefix}_HEADERS", "").strip()
        try:
            headers = json.loads(raw_headers) if raw_headers else {}
        except json.JSONDecodeError as exc:
            raise TargetConfigError(f"{prefix}_HEADERS is not valid JSON: {exc}") from exc
        if not isinstance(headers, dict):
            raise TargetConfigError(f"{prefix}_HEADERS must be a JSON object")
        return cls(
            target_id=target_id,
            method=_env(f"{prefix}_METHOD").upper(),
            url=_env(f"{prefix}_URL"),
            headers={k: str(v) for k, v in headers.items()},
            timeout=float(os.environ.get(f"{prefix}_TIMEOUT", "30")),
        )

    def call(self, body: dict | None = None, json_path: str | None = None) -> CallRecord:
        """Issue the request and return a record. Strict TLS always (httpx verifies
        by default); non-2xx and undecodable bodies are errors, not empty successes."""
        route = f"{self.method} {self.url.split('?', 1)[0]}"
        started = time.monotonic()
        try:
            response = httpx.request(
                self.method,
                self.url,
                json=body,
                headers={"Accept": "application/json", **self.headers},
                timeout=self.timeout,
                follow_redirects=True,
            )
            latency_ms = int((time.monotonic() - started) * 1000)
            response.raise_for_status()
            payload = response.json()
            if json_path:
                payload = extract(payload, json_path)
        except Exception as exc:  # noqa: BLE001 - every failure mode becomes a failed run
            return CallRecord(
                target_id=self.target_id,
                adapter="http",
                route=route,
                arguments_hash=arguments_hash(body),
                latency_ms=int((time.monotonic() - started) * 1000),
                error=f"{type(exc).__name__}: {exc}",
            )
        return CallRecord(
            target_id=self.target_id,
            adapter="http",
            route=route,
            arguments_hash=arguments_hash(body),
            latency_ms=latency_ms,
            raw_response=payload,
        )


# --------------------------------------------------------------------------- #
# mcp adapter
# --------------------------------------------------------------------------- #
PROTOCOL_VERSION = "2025-06-18"


@dataclass
class McpTarget:
    """Streamable-HTTP MCP client.

    The URL comes from the environment and carries whatever credential the server
    expects. Session state lives in the
    `Mcp-Session-Id` header the server hands back at initialize.
    """

    target_id: str
    url: str
    timeout: float = 60.0
    _session_id: str | None = field(default=None, init=False, repr=False)
    _tools: dict[str, dict] | None = field(default=None, init=False, repr=False)

    @classmethod
    def from_env(cls, target_id: str, url_var: str) -> McpTarget:
        return cls(target_id=target_id, url=_env(url_var))

    # -- transport ---------------------------------------------------------- #
    def _post(self, payload: dict) -> dict | None:
        """One JSON-RPC POST. Handles both response encodings the streamable-HTTP
        transport is allowed to use: a JSON body, or an SSE stream carrying the
        reply in a `data:` frame. Returns None for notifications (no reply)."""
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if self._session_id:
            headers["Mcp-Session-Id"] = self._session_id

        response = httpx.post(self.url, json=payload, headers=headers, timeout=self.timeout)
        if response.status_code == 401:
            raise TargetError(f"{self.target_id}: 401 from MCP endpoint (token rejected)")
        response.raise_for_status()

        session_id = response.headers.get("mcp-session-id")
        if session_id:
            self._session_id = session_id

        if response.status_code == 202 or not response.content:
            return None

        content_type = response.headers.get("content-type", "")
        if content_type.startswith("text/event-stream"):
            message = _first_sse_data(response.text)
        else:
            message = response.json()

        if message is None:
            return None
        if "error" in message:
            raise TargetError(f"{self.target_id}: MCP error {message['error']}")
        return message.get("result", {})

    def _initialize(self) -> None:
        if self._session_id is not None:
            return
        self._post(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": {"name": "seismograph", "version": "0.3.1"},
                },
            }
        )
        self._post({"jsonrpc": "2.0", "method": "notifications/initialized"})
        # A server that issues no session id still gets a marker, so initialize
        # runs exactly once per target instance.
        self._session_id = self._session_id or ""

    # -- api ---------------------------------------------------------------- #
    def list_tools(self, refresh: bool = False) -> dict[str, dict]:
        """Read tools/list from the server. This is the only source of tool schemas."""
        if self._tools is not None and not refresh:
            return self._tools
        self._initialize()
        result = self._post({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}) or {}
        tools = result.get("tools")
        if not tools:
            raise TargetError(f"{self.target_id}: tools/list returned no tools")
        self._tools = {t["name"]: t for t in tools}
        return self._tools

    def call_tool(self, name: str, arguments: dict) -> CallRecord:
        """Validate `arguments` against the SERVED inputSchema, then call the tool."""
        started = time.monotonic()
        args_hash = arguments_hash(arguments)
        try:
            tools = self.list_tools()
            if name not in tools:
                raise TargetError(
                    f"{self.target_id}: tool {name!r} not served (have: {sorted(tools)})"
                )
            validate_against_schema(arguments, tools[name].get("inputSchema") or {})
            result = self._post(
                {
                    "jsonrpc": "2.0",
                    "id": 3,
                    "method": "tools/call",
                    "params": {"name": name, "arguments": arguments},
                }
            )
            latency_ms = int((time.monotonic() - started) * 1000)
            if result is None:
                raise TargetError(f"{self.target_id}: tools/call returned no result")
            if result.get("isError"):
                raise TargetError(f"{self.target_id}: tool {name!r} reported isError")
        except Exception as exc:  # noqa: BLE001 - every failure mode becomes a failed run
            return CallRecord(
                target_id=self.target_id,
                adapter="mcp",
                route=name,
                arguments_hash=args_hash,
                latency_ms=int((time.monotonic() - started) * 1000),
                error=f"{type(exc).__name__}: {exc}",
            )
        return CallRecord(
            target_id=self.target_id,
            adapter="mcp",
            route=name,
            arguments_hash=args_hash,
            latency_ms=latency_ms,
            raw_response=result,
        )

    def call(self, body: dict | None = None, json_path: str | None = None) -> CallRecord:
        """The suite runner's interface (app.runner.run_suite), same as HttpTarget.call.

        A suite case's request names the tool in `tool`; everything else in the request
        except `case_id` is the tool's arguments. Nothing is reshaped to fit: call_tool
        validates those arguments against the SERVED inputSchema, so a case written for
        a different tool shape comes back as a failed call naming the mismatch, not as a
        guess at what the server meant.
        """
        request = dict(body or {})
        tool = request.pop("tool", None)
        request.pop("case_id", None)
        if not tool:
            return CallRecord(
                target_id=self.target_id, adapter="mcp", route="(no tool)",
                arguments_hash=arguments_hash(body), latency_ms=0,
                error="TargetError: an MCP suite case must name its tool in request.tool",
            )
        record = self.call_tool(tool, request)
        if record.ok and json_path:
            try:
                record = CallRecord(
                    target_id=record.target_id, adapter="mcp", route=record.route,
                    arguments_hash=record.arguments_hash, latency_ms=record.latency_ms,
                    raw_response=extract(record.raw_response, json_path))
            except TargetError as exc:
                record = CallRecord(
                    target_id=record.target_id, adapter="mcp", route=record.route,
                    arguments_hash=record.arguments_hash, latency_ms=record.latency_ms,
                    error=f"{type(exc).__name__}: {exc}")
        return record


def _first_sse_data(text: str) -> dict | None:
    """Return the first `data:` frame of an SSE body, decoded."""
    for line in text.splitlines():
        if line.startswith("data:"):
            return json.loads(line[5:].strip())
    return None
