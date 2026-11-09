"""The deterministic perturbation generators: same seed in, same variants out, and never
the seed itself (a variant equal to the seed measures nothing)."""
import pytest

from app.engine.contracts import Perturbation
from app.engine.perturb import (
    DETERMINISTIC_PERTURBATIONS,
    DISTRACTORS,
    format_variants,
    irrelevant_context,
    reorderings,
    sentences,
    variants_for,
)

SEED = "Customer bought a blender 12 days ago, unopened. Are they refund eligible?"


def test_sentences_split_on_terminal_punctuation_and_keep_a_trailing_fragment():
    assert sentences(SEED) == ["Customer bought a blender 12 days ago, unopened.",
                               "Are they refund eligible?"]
    assert sentences("One. Two! Three") == ["One.", "Two!", "Three"]
    assert sentences("   ") == []


@pytest.mark.parametrize("perturbation", sorted(DETERMINISTIC_PERTURBATIONS))
def test_every_generator_is_deterministic_and_never_returns_the_seed(perturbation):
    first = variants_for(perturbation, SEED, 12)
    assert first == variants_for(perturbation, SEED, 12)
    assert len(first) == 12
    assert SEED not in first


def test_irrelevant_context_keeps_the_seed_intact_and_alternates_sides():
    variants = irrelevant_context(SEED, 2 * len(DISTRACTORS))
    assert all(SEED in v for v in variants)
    assert variants[0] == f"{DISTRACTORS[0]} {SEED}"
    assert variants[len(DISTRACTORS)] == f"{SEED} {DISTRACTORS[0]}"


def test_reordering_emits_every_other_sentence_order():
    assert reorderings(SEED, 3) == [
        "Are they refund eligible? Customer bought a blender 12 days ago, unopened."] * 3
    three = reorderings("A. B. C.", 5)
    assert len(set(three)) == 5 and "A. B. C." not in three


def test_reordering_refuses_a_single_sentence():
    with pytest.raises(ValueError, match="at least two sentences"):
        reorderings("Is this refundable?", 3)


def test_format_variants_change_surface_only():
    variants = format_variants(SEED, 6)
    assert len(set(variants)) == 6
    squash = lambda s: "".join(s.lower().split()).rstrip(".!?")  # noqa: E731
    assert {squash(v) for v in variants} == {squash(SEED)}


def test_format_variants_exist_even_for_an_input_with_no_letters():
    variants = format_variants("12.", 4)
    assert len(variants) == 4 and "12." not in variants


def test_variants_for_accepts_the_enum_and_rejects_the_rest():
    assert variants_for(Perturbation.format, SEED, 1) == [SEED.upper()]
    with pytest.raises(ValueError, match="no deterministic generator"):
        variants_for(Perturbation.paraphrase, SEED, 1)
    with pytest.raises(ValueError, match="at least 1"):
        variants_for(Perturbation.format, SEED, 0)
