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
    env = os.environ.copy()
    env.update({"APP_ENV": "development", "API_HOST": "127.0.0.1", "API_PORT": str(port)})
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
                 "SMOKE_TEST_TOKEN": os.environ.get("SMOKE_TEST_TOKEN", "dev")})
        if r.returncode != 0 or "SMOKE OK" not in r.stdout:
            fail(f"smoke: {r.stdout.strip()} {r.stderr.strip()}"[:300])
        print("GATE smoke: PASS")
    finally:
        server.terminate()
        try:
            server.wait(timeout=8)
        except Exception:
            server.kill()


def main() -> None:
    r = run("ruff", [PY, "-m", "ruff", "check", "."], 120)
    if r.returncode != 0:
        fail(f"ruff: {r.stdout.strip()[:300]}")
    print("GATE ruff: PASS")

    r = run("pytest", [PY, "-m", "pytest"], 600)
    if r.returncode != 0:
        fail(f"pytest: {(r.stdout + r.stderr).strip()[-300:]}")
    print("GATE pytest: PASS")

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
