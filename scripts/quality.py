"""The quality gate: one number per thing that can be measured, and a floor under each.

    python scripts/quality.py            # exits 0 only when every component is >= 96

"Code quality" is not judged here, it is measured. Nine components, each 0 to 100:

    backend coverage     line + branch coverage of app/ (pytest-cov)
    backend tests        share of tests passing
    backend lint         100 minus one point per ruff finding, pinned ruleset
    backend types        100 minus one point per mypy error on app/
    complexity           share of functions in app/ at cyclomatic complexity <= 10
    frontend coverage    the LOWEST of statements, branches, functions, lines (v8)
    frontend tests       share of tests passing
    frontend lint        100 minus one point per eslint finding
    frontend types       100 minus one point per tsc error

The gate is the minimum, not the mean: a perfect test suite cannot buy back an unlinted
tree. The mean is reported as the headline score and never decides anything.

A component that could not be measured scores 0 and says why. It is never skipped: a
quality report with a hole in it reads as a pass.

Writes quality_report.json and quality_report.md at the repo root.
"""
from __future__ import annotations

import ast
import json
import os
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
WEB = REPO / "web"
FLOOR = 96.0
MAX_COMPLEXITY = 10
RUFF_SELECT = "F,E4,E7,E9,B,I,UP,SIM"
RUFF_IGNORE = "UP042"       # str+Enum -> StrEnum changes str(member); see pyproject.toml
PY_TARGETS = ["app", "scripts", "tests", "alembic"]


def _run(cmd: list[str], cwd: Path, timeout: int, env: dict | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout,
                          env={**os.environ, **(env or {})}, encoding="utf-8", errors="replace")


def _penalty(findings: int) -> float:
    return float(max(0, 100 - findings))


def _component(name: str, score: float, detail: str) -> dict:
    return {"name": name, "score": round(score, 2), "detail": detail, "ok": score >= FLOOR}


def _unmeasured(name: str, why: str) -> dict:
    return _component(name, 0.0, f"NOT MEASURED: {why}")


def backend_tests_and_coverage(tmp: Path) -> list[dict]:
    cov_json, junit = tmp / "coverage.json", tmp / "junit.xml"
    out = _run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-W", "ignore",
                "--cov=app", "--cov-branch", f"--cov-report=json:{cov_json}",
                f"--junitxml={junit}"], REPO, timeout=900,
               env={"WEB_DIR": str(tmp / "no-web-build"), "COVERAGE_FILE": str(tmp / ".coverage")})
    if not junit.is_file() or not cov_json.is_file():
        why = (out.stdout + out.stderr).strip()[-300:]
        return [_unmeasured("backend tests", why), _unmeasured("backend coverage", why)]
    suite = ET.parse(junit).getroot()
    suite = suite if suite.tag == "testsuite" else suite.find("testsuite")
    total = int(suite.get("tests", 0))
    bad = int(suite.get("failures", 0)) + int(suite.get("errors", 0))
    skipped = int(suite.get("skipped", 0))
    ran = total - skipped
    totals = json.loads(cov_json.read_text(encoding="utf-8"))["totals"]
    return [
        _component("backend tests", 100.0 * (ran - bad) / ran if ran else 0.0,
                   f"{ran - bad} of {ran} passed, {skipped} skipped"),
        _component("backend coverage", totals["percent_covered"],
                   f"{totals['covered_lines']} of {totals['num_statements']} statements, "
                   f"{totals['covered_branches']} of {totals['num_branches']} branches"),
    ]


def backend_lint() -> dict:
    out = _run([sys.executable, "-m", "ruff", "check", *PY_TARGETS, "--select", RUFF_SELECT,
                "--ignore", RUFF_IGNORE, "--output-format", "json", "--no-cache"], REPO, timeout=180)
    try:
        findings = len(json.loads(out.stdout))
    except json.JSONDecodeError:
        return _unmeasured("backend lint", (out.stderr or out.stdout).strip()[-300:])
    return _component("backend lint", _penalty(findings),
                      f"{findings} ruff findings, rules {RUFF_SELECT}")


def backend_types() -> dict:
    out = _run([sys.executable, "-m", "mypy", "app", "--no-incremental"], REPO, timeout=600)
    lines = [ln for ln in out.stdout.splitlines() if ": error:" in ln]
    if out.returncode not in (0, 1):
        return _unmeasured("backend types", (out.stderr or out.stdout).strip()[-300:])
    return _component("backend types", _penalty(len(lines)), f"{len(lines)} mypy errors on app/")


def complexity() -> dict:
    functions = 0
    for path in (REPO / "app").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        functions += sum(isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef) for n in ast.walk(tree))
    out = _run([sys.executable, "-m", "ruff", "check", "app", "--select", "C901",
                "--config", f"lint.mccabe.max-complexity = {MAX_COMPLEXITY}",
                "--output-format", "json", "--no-cache"], REPO, timeout=180)
    try:
        over = json.loads(out.stdout)
    except json.JSONDecodeError:
        return _unmeasured("complexity", (out.stderr or out.stdout).strip()[-300:])
    if not functions:
        return _unmeasured("complexity", "no functions found under app/")
    names = ", ".join(sorted(f["message"].split("`")[1] for f in over)) or "none"
    return _component("complexity", 100.0 * (functions - len(over)) / functions,
                      f"{functions - len(over)} of {functions} functions at complexity <= "
                      f"{MAX_COMPLEXITY}. Over: {names}")


def frontend(tmp: Path) -> list[dict]:
    names = ["frontend tests", "frontend coverage", "frontend lint", "frontend types"]
    npx = shutil.which("npx")
    if not npx or not (WEB / "node_modules").is_dir():
        return [_unmeasured(n, "npx or web/node_modules missing; run `npm ci` in web/") for n in names]
    out: list[dict] = []

    gen = _run([shutil.which("node") or "node", "scripts/published.mjs"], WEB, timeout=60)
    if gen.returncode != 0:
        return [_unmeasured(n, gen.stderr.strip()[-300:]) for n in names]

    results = tmp / "vitest.json"
    _run([npx, "vitest", "run", "--coverage", "--reporter=json", f"--outputFile={results}"],
         WEB, timeout=900)
    summary = WEB / "coverage" / "coverage-summary.json"
    if results.is_file():
        data = json.loads(results.read_text(encoding="utf-8"))
        total, passed = data["numTotalTests"], data["numPassedTests"]
        out.append(_component("frontend tests", 100.0 * passed / total if total else 0.0,
                              f"{passed} of {total} passed"))
    else:
        out.append(_unmeasured("frontend tests", "vitest wrote no result file"))
    if results.is_file() and summary.is_file():
        totals = json.loads(summary.read_text(encoding="utf-8"))["total"]
        parts = {k: totals[k]["pct"] for k in ("statements", "branches", "functions", "lines")}
        out.append(_component("frontend coverage", min(parts.values()),
                              ", ".join(f"{k} {v}%" for k, v in parts.items())))
    else:
        out.append(_unmeasured("frontend coverage", "no coverage summary written"))

    lint = _run([npx, "eslint", ".", "--format", "json"], WEB, timeout=300)
    try:
        findings = sum(f["errorCount"] + f["warningCount"] for f in json.loads(lint.stdout))
        out.append(_component("frontend lint", _penalty(findings), f"{findings} eslint findings"))
    except json.JSONDecodeError:
        out.append(_unmeasured("frontend lint", (lint.stderr or lint.stdout).strip()[-300:]))

    tsc = _run([npx, "tsc", "--noEmit"], WEB, timeout=300)
    errors = sum(": error TS" in ln for ln in tsc.stdout.splitlines())
    if tsc.returncode != 0 and not errors:
        out.append(_unmeasured("frontend types", (tsc.stderr or tsc.stdout).strip()[-300:]))
    else:
        out.append(_component("frontend types", _penalty(errors), f"{errors} tsc errors"))
    return out


def render(report: dict) -> str:
    lines = [
        "# Quality report",
        "",
        f"Generated {report['generated_at']} by `python scripts/quality.py` at commit "
        f"`{report['commit']}`.",
        "",
        f"**Gate: {'PASS' if report['passed'] else 'FAIL'}.** The lowest component is "
        f"{report['minimum']:.2f} against a floor of {FLOOR:.0f}. Mean of the components: "
        f"{report['score']:.2f}.",
        "",
        "| Component | Score | Floor met | Measured |",
        "|---|---|---|---|",
    ]
    for c in report["components"]:
        lines.append(f"| {c['name']} | {c['score']:.2f} | {'yes' if c['ok'] else 'NO'} | {c['detail']} |")
    lines += [
        "",
        "The gate is the minimum, not the mean. A component that could not be measured scores 0.",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="seismo-quality-") as raw:
        tmp = Path(raw)
        components = [*backend_tests_and_coverage(tmp), backend_lint(), backend_types(),
                      complexity(), *frontend(tmp)]
    commit = _run(["git", "rev-parse", "--short", "HEAD"], REPO, timeout=30).stdout.strip() or "unknown"
    scores = [c["score"] for c in components]
    report = {
        "generated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "commit": commit, "floor": FLOOR,
        "score": round(sum(scores) / len(scores), 2), "minimum": min(scores),
        "passed": all(c["ok"] for c in components), "components": components,
    }
    (REPO / "quality_report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8",
                                              newline="\n")
    text = render(report)
    (REPO / "quality_report.md").write_text(text, encoding="utf-8", newline="\n")
    print(text)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
