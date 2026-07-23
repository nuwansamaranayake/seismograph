"""Embedders: an explicit, typed choice — never a fallback (Standard 3).

HashingEmbedder is deterministic and keyless: it measures nothing about semantics beyond
token overlap, which is exactly what the golden-defect eval needs (byte-reproducible in CI).
OpenRouterEmbedder is the real semantic instrument, used by the metamorphic back-check and
live canonicalization. The caller always names which one it wants.
"""
from __future__ import annotations

import hashlib
import math
import re
from typing import Protocol

import httpx

_TOKEN = re.compile(r"[a-z0-9]+")


class Embedder(Protocol):
    name: str
    def embed(self, texts: list[str]) -> list[list[float]]: ...


class HashingEmbedder:
    """Deterministic bag-of-hashed-tokens vectors. No network, no key, no drift."""

    name = "hashing"

    def __init__(self, dim: int = 256):
        self._dim = dim

    def embed(self, texts: list[str]) -> list[list[float]]:
        out = []
        for text in texts:
            v = [0.0] * self._dim
            for tok in _TOKEN.findall(text.lower()):
                h = int.from_bytes(hashlib.sha256(tok.encode()).digest()[:8], "big")
                v[h % self._dim] += 1.0
            norm = math.sqrt(sum(x * x for x in v)) or 1.0
            out.append([x / norm for x in v])
        return out


class OpenRouterEmbedder:
    """Real embeddings via the OpenRouter embeddings endpoint. Refuses to run blind."""

    name = "openrouter"

    def __init__(self, api_key: str, model: str,
                 base_url: str = "https://openrouter.ai/api/v1"):
        if not api_key:
            raise RuntimeError("OPENROUTER_API_KEY is not set. Refusing to run blind.")
        if not model:
            raise RuntimeError("EMBEDDING_MODEL is not set. Refusing to guess a model.")
        self._key = api_key
        self._model = model
        self._url = base_url.rstrip("/") + "/embeddings"

    def embed(self, texts: list[str]) -> list[list[float]]:
        r = httpx.post(
            self._url,
            headers={"Authorization": f"Bearer {self._key}"},
            json={"model": self._model, "input": texts},
            timeout=60,
        )
        r.raise_for_status()
        data = sorted(r.json()["data"], key=lambda d: d["index"])
        return [d["embedding"] for d in data]


def cosine(a: list[float], b: list[float]) -> float:
    num = sum(x * y for x, y in zip(a, b))
    da = math.sqrt(sum(x * x for x in a))
    db = math.sqrt(sum(x * x for x in b))
    if da == 0.0 or db == 0.0:
        return 0.0
    return num / (da * db)
