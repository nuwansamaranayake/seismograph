"""Suite definitions — what to call, what to check, which cases run today.

A suite is a directory (`suites/<name>/`) holding:

    suite.yaml          target shape, layers, profiles, version
    cases/*.json        one golden case each: request + reference chart facts
    policy/*.json       the `assert` policy each layer applies

The suite file is the contract between the runner and the eval author. Nothing
here calls a model and nothing here decides pass/fail — it only loads and
selects. Loading is strict: a case naming a layer that does not exist, or a
profile asking for a missing policy file, raises rather than quietly running a
smaller suite than the author wrote (Standard 3).
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import yaml


class SuiteError(RuntimeError):
    """A suite directory is missing, malformed, or internally inconsistent."""


@dataclass(frozen=True)
class Layer:
    """One evaluation layer. `check` names the check type in app/checks.py."""

    name: str
    check: str
    policy: dict


@dataclass(frozen=True)
class Case:
    """One golden case: the request sent to the target and the reference facts
    every layer compares against. `source` records provenance — never customer
    data (docs/gates-spec.md g3)."""

    id: str
    source: str
    request: dict
    reference: dict


@dataclass(frozen=True)
class Profile:
    """`repeats` runs per case; `rotate` limits the daily window to N cases."""

    name: str
    repeats: int
    rotate: int | None


@dataclass(frozen=True)
class Suite:
    name: str
    version: str
    target_id: str
    json_path: str | None
    layers: tuple[Layer, ...]
    cases: tuple[Case, ...]
    profiles: dict[str, Profile]
    root: Path

    def profile(self, name: str) -> Profile:
        if name not in self.profiles:
            raise SuiteError(
                f"suite {self.name}: no profile {name!r} (have: {sorted(self.profiles)})"
            )
        return self.profiles[name]

    def select(self, profile: Profile, on: date) -> tuple[Case, ...]:
        """The cases this profile runs on `on`.

        A rotating profile walks a fixed-size window over the case list keyed by
        the date, so two runs on the same day pick the same cases (the gate runs
        the CLI twice) while consecutive days cover the whole set.
        """
        if profile.rotate is None or profile.rotate >= len(self.cases):
            return self.cases
        start = on.toordinal() * profile.rotate % len(self.cases)
        doubled = self.cases + self.cases
        return doubled[start:start + profile.rotate]

    def content_sha256_16(self) -> str:
        """A stable digest over every file that defines this suite. The report
        header carries it, so a report can never be read against a suite that has
        since changed underneath it.

        Line endings are normalised first: with core.autocrlf a Windows checkout holds
        CRLF and a Linux runner holds LF for the same commit, and a digest over raw
        bytes would refuse the committed baseline on one of them."""
        digest = hashlib.sha256()
        for path in sorted(self.root.rglob("*")):
            if path.is_file() and "baseline" not in path.parts:
                digest.update(path.relative_to(self.root).as_posix().encode())
                digest.update(path.read_bytes().replace(b"\r\n", b"\n"))
        return digest.hexdigest()[:16]


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise SuiteError(f"missing {path}") from exc
    except json.JSONDecodeError as exc:
        raise SuiteError(f"{path}: {exc}") from exc


def load_suite(root: Path) -> Suite:
    spec_path = root / "suite.yaml"
    if not spec_path.exists():
        raise SuiteError(f"no suite.yaml under {root}")
    spec = yaml.safe_load(spec_path.read_text(encoding="utf-8")) or {}

    layers = tuple(
        Layer(name=name, check=body["check"], policy=_read_json(root / body["policy"]))
        for name, body in (spec.get("layers") or {}).items()
    )
    if not layers:
        raise SuiteError(f"{spec_path}: no layers declared")

    cases = []
    for path in sorted((root / "cases").glob("*.json")):
        raw = _read_json(path)
        cases.append(
            Case(
                id=raw["id"],
                source=raw["source"],
                request=raw["request"],
                reference=raw["reference"],
            )
        )
    if not cases:
        raise SuiteError(f"{root / 'cases'}: no cases")

    profiles = {
        name: Profile(name=name, repeats=int(body["repeats"]), rotate=body.get("rotate"))
        for name, body in (spec.get("profiles") or {}).items()
    }
    if not profiles:
        raise SuiteError(f"{spec_path}: no profiles declared")

    target = spec.get("target") or {}
    return Suite(
        name=spec["suite"],
        version=spec["version"],
        target_id=target.get("id") or spec["suite"],
        json_path=target.get("json_path"),
        layers=layers,
        cases=tuple(cases),
        profiles=profiles,
        root=root,
    )
