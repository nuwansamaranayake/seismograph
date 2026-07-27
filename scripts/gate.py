"""Loop gate: ruff, pytest, live smoke, eval. Exits nonzero on any failure.

The single objective gate for build loops (AiGNITE Loop Kit). Every check is observed,
every subprocess carries a timeout. eval.py counts as SKIP while it still raises its
deliberate "lands in Phase 1" NotImplementedError; any other eval failure fails the gate.
"""
from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx

REPO = Path(__file__).resolve().parent.parent
PY = sys.executable
PENDING = "eval harness lands in Phase 1"


def run(name: str, cmd: list[str], timeout: int, env: dict | None = None) -> subprocess.CompletedProcess:
    e = os.environ.copy()
    if env:
        e.update(env)
    return subprocess.run(cmd, cwd=str(REPO), env=e, capture_output=True, text=True, timeout=timeout)


def fail(reason: str) -> None:
    print(f"GATE FAIL: {reason}", file=sys.stderr)
    sys.exit(1)


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def smoke() -> None:
    port = free_port()
    # Resolve the token ONCE and inject it into the spawned server's environment (env vars
    # override .env in pydantic-settings). Otherwise the server reads whatever the repo .env
    # holds and the client-side token mismatches: a false red on a healthy build, or an
    # auth-off pass that never exercises the bearer path.
    token = os.environ.get("SMOKE_TEST_TOKEN", "dev")
    env = os.environ.copy()
    env.update({"APP_ENV": "development", "API_HOST": "127.0.0.1", "API_PORT": str(port),
                "SMOKE_TEST_TOKEN": token})
    server = subprocess.Popen(
        [PY, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(port),
         "--log-level", "warning"],
        cwd=str(REPO), env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        deadline = time.time() + 25
        up = False
        while time.time() < deadline:
            try:
                if httpx.get(f"http://127.0.0.1:{port}/health", timeout=2).status_code == 200:
                    up = True
                    break
            except Exception:
                time.sleep(0.4)
        if not up:
            fail("smoke: server never became healthy")
        r = run("smoke", [PY, "scripts/smoke_test.py"], 60,
                {"API_HOST": "127.0.0.1", "API_PORT": str(port),
                 "SMOKE_TEST_TOKEN": token})
        if r.returncode != 0 or "SMOKE OK" not in r.stdout:
            fail(f"smoke: {r.stdout.strip()} {r.stderr.strip()}"[:300])
        print("GATE smoke: PASS")
    finally:
        server.terminate()
        try:
            server.wait(timeout=8)
        except Exception:
            server.kill()



PUBLIC_ROUTES = {
    "/health",                                  # uptime monitoring
    "/api/v1/demo",                             # dev fixture; 503 outside development
    "/openapi.json", "/docs", "/docs/oauth2-redirect", "/redoc",
}


def _walk_routes(routes):
    """Yield leaf routes.

    FastAPI >= 0.140 nests an included router under `_IncludedRouter.original_router`
    instead of flattening it into `app.routes`; older versions expose `.routes` or flatten
    directly. Walking only the top level silently sees the scaffold routes and none of the
    business routes, which is how a check like this passes while proving nothing.
    """
    for r in routes:
        original = getattr(r, "original_router", None)
        sub = (getattr(original, "routes", None) if original is not None
               else getattr(r, "routes", None))
        if sub:
            yield from _walk_routes(sub)
        else:
            yield r


def route_auth() -> None:
    """Class check, not an instance check.

    Every non-public route must accept an `authorization` parameter. A test asserting that
    nine specific handlers return 401 cannot protect the tenth handler added next week;
    enumerating the router can. See the 2026-07-27 unauthenticated-reads postmortem.
    """
    import inspect
    sys.path.insert(0, str(REPO))
    from app.main import app

    guarded, unguarded = [], []
    for r in _walk_routes(app.routes):
        path = getattr(r, "path", None)
        endpoint = getattr(r, "endpoint", None)
        if not path or endpoint is None or path in PUBLIC_ROUTES:
            continue
        if "authorization" in inspect.signature(endpoint).parameters:
            guarded.append(path)
        else:
            methods = ",".join(sorted(getattr(r, "methods", None) or []))
            unguarded.append(f"{methods} {path}")

    if not guarded and not unguarded:
        fail("route-auth: enumerated ZERO business routes. The walker cannot see this "
             "FastAPI version's router layout, so the check proves nothing. Refusing to "
             "report a pass.")
    if unguarded:
        fail(f"route-auth: {len(unguarded)} non-public route(s) accept no authorization "
             f"parameter: {unguarded}")
    print(f"GATE route-auth: PASS ({len(guarded)} business routes, all bearer-gated)")


def main() -> None:
    r = run("ruff", [PY, "-m", "ruff", "check", "."], 120)
    if r.returncode != 0:
        fail(f"ruff: {r.stdout.strip()[:300]}")
    print("GATE ruff: PASS")

    r = run("pytest", [PY, "-m", "pytest"], 600)
    if r.returncode != 0:
        fail(f"pytest: {(r.stdout + r.stderr).strip()[-300:]}")
    print("GATE pytest: PASS")

    route_auth()

    smoke()

    r = run("eval", [PY, "scripts/eval.py"], 900)
    if r.returncode == 0:
        print("GATE eval: PASS")
    elif PENDING in (r.stdout + r.stderr):
        print("GATE eval: SKIP (pending Phase 1; flips to enforced when the real harness lands)")
    else:
        fail(f"eval: {(r.stdout + r.stderr).strip()[-300:]}")

    print("GATE OK")


if __name__ == "__main__":
    main()
