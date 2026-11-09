"""Jev (TypeSafe System One, served through OpenRouter) as a system under test.

The adapter sends one `state` and a map of typed questions to
POST {TYPESAFE_BASE_URL}/v1/systemone and maps the answer back onto
Seismograph's call record. Request shape follows the TypeSafe API reference
(https://docs.typesafe.ai/api.md) and the OpenRouter guide
(https://openrouter.ai/docs/guides/community/typesafe-sdk.md), the same shape
a local smoke test verified live on 2026-09-21. No field is
invented here; the SDK builds the body.

Doctrine (Standard 3, EVAL.md): a malformed answer raises. Nothing here returns
a default, a zero, or an empty vector in place of a model answer. A missing
credential refuses to construct the target. The key is never logged.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from typing import Any, cast

from .targets import CallRecord, TargetConfigError, TargetError, arguments_hash

ADAPTER = "jev"
SYSTEM_ONE_ROUTE = "/v1/systemone"
REQUIRED_ENV = ("TYPESAFE_API_KEY", "TYPESAFE_BASE_URL")
# The API serves each probability rounded to two decimals (observed live 2026-09-21:
# a 57-option vector summed to 0.99). A rounded vector can miss 1.0 by up to half a
# step per option, so the tolerance is the larger of 0.01 and 0.005 x options.
PROB_TOLERANCE = 0.01
PROB_ROUNDING_STEP = 0.01


def prob_tolerance(n_options: int) -> float:
    return max(PROB_TOLERANCE, PROB_ROUNDING_STEP / 2 * n_options)


def hydrate_env_from_user_scope() -> list[str]:
    """Windows only: copy TYPESAFE_* from the User-scope registry into the process
    env when the process did not inherit them (Claude Code sessions started before
    the variables were set). Returns the names it filled. Values are never printed.
    The adapter itself reads os.environ only, so a test can prove the refusal path."""
    filled: list[str] = []
    if os.name != "nt":
        return filled
    try:
        import winreg
    except ImportError:  # pragma: no cover
        return filled
    for name in REQUIRED_ENV:
        if os.environ.get(name, "").strip():
            continue
        try:
            # typeshed's winreg is empty off Windows and mypy does not treat the os.name
            # guard above as a platform check, so Linux reported errors Windows did not.
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:  # type: ignore[attr-defined,unused-ignore]
                value, _ = winreg.QueryValueEx(key, name)  # type: ignore[attr-defined,unused-ignore]
        except OSError:
            continue
        if str(value).strip():
            os.environ[name] = str(value).strip()
            filled.append(name)
    return filled


@dataclass(frozen=True)
class JevAnswer:
    """One question's answer, with its full probability vector."""

    question_id: str
    type: str                    # noul | choice | score
    answer: float | str          # noul probability, chosen option, or expected score
    probabilities: dict[str, float]
    confidence: float

    def decision(self, cutoff: float) -> bool | str:
        """The binary or categorical decision Seismograph gates on."""
        if self.type == "noul":
            return float(self.answer) >= cutoff
        return str(self.answer)


@dataclass(frozen=True)
class JevCallRecord(CallRecord):
    """Seismograph's run record plus the fields a typed-judgment SUT adds."""

    model: str = ""
    probe_id: str = ""
    run_index: int = 0
    answers: dict[str, JevAnswer] = field(default_factory=dict)
    input_tokens: int | None = None
    output_tokens: int | None = None
    usage_cost: float | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "target_id": self.target_id, "adapter": self.adapter, "route": self.route,
            "arguments_hash": self.arguments_hash, "latency_ms": self.latency_ms,
            "error": self.error, "created_at": self.created_at.isoformat(),
            "model": self.model, "probe_id": self.probe_id, "run_index": self.run_index,
            "answers": {
                q: {"type": a.type, "answer": a.answer, "probabilities": a.probabilities,
                    "confidence": a.confidence}
                for q, a in self.answers.items()
            },
            "input_tokens": self.input_tokens, "output_tokens": self.output_tokens,
            "usage_cost": self.usage_cost,
        }

    @classmethod
    def from_json(cls, row: dict[str, Any]) -> JevCallRecord:
        from datetime import datetime

        answers = {
            q: JevAnswer(q, a["type"], a["answer"], dict(a["probabilities"]), float(a["confidence"]))
            for q, a in row["answers"].items()
        }
        return cls(
            target_id=row["target_id"], adapter=row["adapter"], route=row["route"],
            arguments_hash=row["arguments_hash"], latency_ms=int(row["latency_ms"]),
            raw_response=None, error=row.get("error"),
            created_at=datetime.fromisoformat(row["created_at"]),
            model=row["model"], probe_id=row["probe_id"], run_index=int(row["run_index"]),
            answers=answers, input_tokens=row.get("input_tokens"),
            output_tokens=row.get("output_tokens"), usage_cost=row.get("usage_cost"),
        )


def _num(value: Any, where: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TargetError(f"malformed answer: {where} is {value!r}, expected a number")
    return float(value)


def map_answers(raw: Any, questions: dict[str, dict]) -> dict[str, JevAnswer]:
    """Strictly map a System One response body onto JevAnswer objects.

    Every declared question must be answered with the declared type. Choice and
    score answers must carry a probability vector over the declared options that
    sums to one within PROB_TOLERANCE. Anything else raises TargetError.
    """
    if not isinstance(raw, dict):
        raise TargetError(f"malformed response: body is {type(raw).__name__}, expected object")
    answers = raw.get("answers")
    if not isinstance(answers, dict):
        raise TargetError("malformed response: 'answers' missing or not an object")
    mapped: dict[str, JevAnswer] = {}
    for qid, q in questions.items():
        a = answers.get(qid)
        if not isinstance(a, dict):
            raise TargetError(f"malformed response: no answer for question {qid!r}")
        qtype = q["type"]
        if a.get("type") != qtype:
            raise TargetError(f"malformed response: {qid} answered as {a.get('type')!r}, asked {qtype!r}")
        if qtype == "noul":
            p = _num(a.get("noul"), f"{qid}.noul")
            if not 0.0 <= p <= 1.0:
                raise TargetError(f"malformed response: {qid}.noul={p} outside [0, 1]")
            mapped[qid] = JevAnswer(qid, "noul", p, {"true": p, "false": 1.0 - p}, max(p, 1.0 - p))
            continue
        probs = a.get("probabilities")
        if not isinstance(probs, dict) or not probs:
            raise TargetError(f"malformed response: {qid}.probabilities missing")
        vector = {str(k): _num(v, f"{qid}.probabilities[{k}]") for k, v in probs.items()}
        total = sum(vector.values())
        tol = prob_tolerance(len(vector))
        if abs(total - 1.0) > tol + 1e-9:
            raise TargetError(
                f"malformed response: {qid} probabilities sum to {total:.4f} "
                f"(tolerance {tol:.3f} for {len(vector)} options)"
            )
        confidence = _num(a.get("confidence"), f"{qid}.confidence")
        if qtype == "choice":
            options = set(q["criteria"])
            chosen = a.get("choice")
            if chosen not in options:
                raise TargetError(f"malformed response: {qid}.choice={chosen!r} not in declared options")
            if set(vector) != {str(o) for o in options}:
                raise TargetError(f"malformed response: {qid} probability keys differ from declared options")
            mapped[qid] = JevAnswer(qid, "choice", str(chosen), vector, confidence)
        elif qtype == "score":
            score = _num(a.get("score"), f"{qid}.score")
            n_levels = len(q["criteria"])
            if set(vector) != {str(i) for i in range(n_levels)}:
                raise TargetError(f"malformed response: {qid} probability keys differ from declared levels")
            mapped[qid] = JevAnswer(qid, "score", score, vector, confidence)
        else:
            raise TargetError(f"contract declares unknown question type {qtype!r} for {qid}")
    return mapped


def map_usage(raw: dict[str, Any]) -> tuple[int, int | None, float | None]:
    usage = raw.get("usage")
    if not isinstance(usage, dict):
        raise TargetError("malformed response: 'usage' missing")
    inp = usage.get("input_tokens")
    if isinstance(inp, bool) or not isinstance(inp, int) or inp <= 0:
        raise TargetError(f"malformed response: usage.input_tokens={inp!r}, expected > 0")
    out = usage.get("output_tokens")
    cost = usage.get("cost")
    return inp, (out if isinstance(out, int) else None), (float(cost) if isinstance(cost, (int, float)) else None)


class JevTarget:
    """A Jev model reached through the TypeSafe SDK."""

    adapter = ADAPTER

    def __init__(self, model: str, *, api_key: str, base_url: str, timeout: float = 30.0,
                 transport: Any = None, target_id: str | None = None) -> None:
        if not model.strip():
            raise TargetConfigError("jev target needs a model id (pin it, e.g. jev-1.13)")
        from typesafe_sdk import TypeSafeClient

        self.model = model
        self.target_id = target_id or f"jev:{model}"
        self.base_url = base_url.rstrip("/")
        self._client = TypeSafeClient(api_key=api_key, base_url=self.base_url, model=model,
                                      timeout=timeout, transport=transport)

    @classmethod
    def from_env(cls, model: str, *, timeout: float = 30.0, transport: Any = None,
                 target_id: str | None = None) -> JevTarget:
        """Refuse to build a target when either credential variable is absent from
        the process environment. Names are reported; values never are."""
        missing = [n for n in REQUIRED_ENV if not os.environ.get(n, "").strip()]
        if missing:
            raise TargetConfigError(
                f"jev target refused: missing environment variable(s) {', '.join(missing)}; "
                "set them at User scope and restart, or hydrate_env_from_user_scope() first"
            )
        return cls(model, api_key=os.environ["TYPESAFE_API_KEY"].strip(),
                   base_url=os.environ["TYPESAFE_BASE_URL"].strip(), timeout=timeout,
                   transport=transport, target_id=target_id)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> JevTarget:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def call(self, state: Any, questions: dict[str, dict], *, probe_id: str = "",
             run_index: int = 0) -> JevCallRecord:
        """One System One evaluation. Raises TargetError on any HTTP failure or
        malformed body; the message carries the HTTP status and body."""
        from typesafe_sdk import (
            TypeSafeAPIConnectionError,
            TypeSafeAPIError,
            TypeSafeAPIResponseValidationError,
        )

        args = {"model": self.model, "state": state, "questions": questions}
        t0 = time.perf_counter()
        try:
            # The SDK types `questions` as its own models and also accepts the plain dicts a
            # contract carries (it builds the request body from them); mypy sees only the former.
            result = self._client.system_one(
                state=state, questions=cast(Any, questions), model=self.model)
        except TypeSafeAPIResponseValidationError as exc:
            # The SDK's own schema rejected the body. Surface it as malformed, never default.
            raise TargetError(f"malformed response: SDK validation failed: {exc}") from exc
        except TypeSafeAPIError as exc:
            body = exc.body if isinstance(exc.body, str) else json.dumps(exc.body)
            raise TargetError(f"jev HTTP {exc.status} at {SYSTEM_ONE_ROUTE}: {body[:1000]}") from exc
        except TypeSafeAPIConnectionError as exc:
            raise TargetError(f"jev connection error at {SYSTEM_ONE_ROUTE}: {exc}") from exc
        latency_ms = int((time.perf_counter() - t0) * 1000)
        http = result.raw_http_response
        if http.status_code != 200:
            raise TargetError(f"jev HTTP {http.status_code}: {http.text[:1000]}")
        raw = json.loads(http.content)
        answers = map_answers(raw, questions)
        input_tokens, output_tokens, cost = map_usage(raw)
        model_field = str(raw.get("model", ""))
        if "jev" not in model_field.lower():
            raise TargetError(f"response model {model_field!r} is not a Jev model")
        return JevCallRecord(
            target_id=self.target_id, adapter=ADAPTER, route=SYSTEM_ONE_ROUTE,
            arguments_hash=arguments_hash(args), latency_ms=latency_ms, raw_response=raw,
            error=None, model=model_field, probe_id=probe_id, run_index=run_index,
            answers=answers, input_tokens=input_tokens, output_tokens=output_tokens,
            usage_cost=cost,
        )
