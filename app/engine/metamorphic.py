"""Metamorphic paraphrase invariant: perception proposes, verification disposes.

The LLM (extraction model, JSON-schema output via the groundwork gateway) generates
paraphrase candidates. A deterministic back-check — embedding cosine similarity against the
seed — accepts or rejects each candidate before it may enter the probe bank. Rejected
variants are kept (accepted=False) for the failure gallery; nothing is silently dropped.

Phase 1 back-check is embedding-only; NLI entailment joins in Phase 2 with the full
invariant set (see LOOP_STATE DECISION log).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .embedding import Embedder, cosine

# Below this cosine similarity a candidate no longer restates the seed; above ~0.99 it is a
# trivial copy. Bounds are deliberately conservative for Phase 1.
MIN_SIMILARITY = 0.60
MAX_SIMILARITY = 0.995

PARAPHRASE_SCHEMA = {
    "name": "paraphrases",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "paraphrases": {
                "type": "array",
                "items": {"type": "string"},
            }
        },
        "required": ["paraphrases"],
        "additionalProperties": False,
    },
}


class CompletesJson(Protocol):
    """The slice of groundwork.LLMGateway this module needs. Tests inject a typed stub;
    production injects the real gateway. Explicit either way — never a silent mock."""

    def complete(self, *, model: str, messages: list[dict],
                 json_schema: dict | None = None, temperature: float = 0.0): ...


@dataclass(frozen=True)
class Variant:
    seed_input: str
    text: str
    back_check_score: float
    accepted: bool
    reason: str          # "ok" | "too_dissimilar" | "trivial_copy" | "empty"


def generate_paraphrases(
    gateway: CompletesJson,
    model: str,
    seed_input: str,
    n: int,
    embedder: Embedder,
) -> list[Variant]:
    """Ask for n paraphrase candidates; back-check each. Returns ALL candidates with their
    verdicts — callers use only accepted ones, and rejected ones feed the failure gallery."""
    if not model:
        raise RuntimeError("LLM_MODEL_EXTRACTION is not set. Refusing to guess a model.")
    result = gateway.complete(
        model=model,
        messages=[
            {"role": "system",
             "content": ("Rewrite the user's text as paraphrases that preserve every fact, "
                         "constraint, and number exactly. Vary wording and sentence "
                         "structure only. Return JSON.")},
            {"role": "user",
             "content": f"Produce {n} distinct paraphrases of:\n\n{seed_input}"},
        ],
        json_schema=PARAPHRASE_SCHEMA,
    )
    candidates = [c.strip() for c in result.get("paraphrases", [])][:n]

    variants: list[Variant] = []
    if not candidates:
        return variants
    vecs = embedder.embed([seed_input] + candidates)
    seed_vec, cand_vecs = vecs[0], vecs[1:]
    for text, vec in zip(candidates, cand_vecs):
        if not text:
            variants.append(Variant(seed_input, text, 0.0, False, "empty"))
            continue
        score = cosine(seed_vec, vec)
        if score < MIN_SIMILARITY:
            variants.append(Variant(seed_input, text, score, False, "too_dissimilar"))
        elif score > MAX_SIMILARITY and text.lower() == seed_input.lower():
            variants.append(Variant(seed_input, text, score, False, "trivial_copy"))
        else:
            variants.append(Variant(seed_input, text, score, True, "ok"))
    return variants
