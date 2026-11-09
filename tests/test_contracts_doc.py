"""contracts.md is checked against the served OpenAPI spec, in both directions.

Standard 6 says every frontend call maps to a backend endpoint. A table nobody diffs
goes stale the first week: this test fails when a route is added without a row, and
when a row claims `implemented` for a route that does not exist.
"""
import re
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app

DOC = (Path(__file__).resolve().parent.parent / "contracts.md").read_text(encoding="utf-8")
ROW = re.compile(r"^\|[^|]*\|\s*(GET|POST|PUT|DELETE|PATCH)\s*\|\s*`([^`]+)`\s*\|\s*([^|]+?)\s*\|", re.M)


def _documented() -> dict[tuple[str, str], str]:
    return {(method, path): status for method, path, status in ROW.findall(DOC)}


def _served() -> set[tuple[str, str]]:
    spec = TestClient(app).get("/openapi.json").json()
    return {(method.upper(), path) for path, item in spec["paths"].items() for method in item}


def _normalise(path: str) -> str:
    return re.sub(r"\{[^}]+\}", "{}", path)


def test_every_served_route_has_a_row():
    documented = {(m, _normalise(p)) for m, p in _documented()}
    missing = sorted((m, p) for m, p in _served() if (m, _normalise(p)) not in documented)
    assert missing == [], f"routes served but absent from contracts.md: {missing}"


def test_every_implemented_row_is_actually_served():
    served = {(m, _normalise(p)) for m, p in _served()}
    # `/` and `/llms.txt` are served outside the schema (include_in_schema=False).
    outside_schema = {("GET", "/"), ("GET", "/llms.txt")}
    stale = sorted((m, p) for (m, p), status in _documented().items()
                   if status == "implemented" and (m, p) not in outside_schema
                   and (m, _normalise(p)) not in served)
    assert stale == [], f"contracts.md says implemented, not served: {stale}"


def test_planned_rows_are_not_served():
    served = {(m, _normalise(p)) for m, p in _served()}
    early = [(m, p) for (m, p), status in _documented().items()
             if status.startswith("planned") and (m, _normalise(p)) in served]
    assert early == [], f"contracts.md still says planned for a served route: {early}"
