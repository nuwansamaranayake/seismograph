import pytest

from app.engine.embedding import HashingEmbedder
from app.engine.metamorphic import generate_paraphrases, Variant


class StubGateway:
    """Typed test double, injected explicitly (never a silent fallback in app code)."""

    def __init__(self, paraphrases):
        self.paraphrases = paraphrases
        self.calls = []

    def complete(self, *, model, messages, json_schema=None, temperature=0.0):
        self.calls.append({"model": model, "json_schema": json_schema})
        return {"paraphrases": self.paraphrases}


SEED = "Customer bought a blender 12 days ago, unopened. Are they refund eligible?"


def test_good_paraphrase_accepted_bad_rejected():
    gw = StubGateway([
        "A customer purchased a blender 12 days ago and never opened it. Refund eligible?",
        "The weather in Lisbon is lovely in spring.",
    ])
    variants = generate_paraphrases(gw, "m", SEED, 2, HashingEmbedder())
    assert [v.accepted for v in variants] == [True, False]
    assert variants[1].reason == "too_dissimilar"
    assert gw.calls[0]["json_schema"] is not None      # structured output demanded


def test_trivial_copy_rejected():
    gw = StubGateway([SEED])
    variants = generate_paraphrases(gw, "m", SEED, 1, HashingEmbedder())
    assert variants[0].accepted is False
    assert variants[0].reason == "trivial_copy"


def test_rejections_are_kept_not_dropped():
    gw = StubGateway(["", "totally unrelated text about sailing boats"])
    variants = generate_paraphrases(gw, "m", SEED, 2, HashingEmbedder())
    assert len(variants) == 2                     # nothing silently dropped
    assert all(not v.accepted for v in variants)


def test_missing_model_refuses():
    with pytest.raises(RuntimeError, match="Refusing to guess"):
        generate_paraphrases(StubGateway([]), "", SEED, 2, HashingEmbedder())


def test_variant_carries_provenance():
    gw = StubGateway(["A buyer got a blender 12 days ago, still unopened; refund eligible?"])
    v: Variant = generate_paraphrases(gw, "m", SEED, 1, HashingEmbedder())[0]
    assert v.seed_input == SEED and 0.0 < v.back_check_score <= 1.0
