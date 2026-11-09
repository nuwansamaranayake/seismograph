"""Synthetic systems under test with programmable defects.

These are the golden-defect suite's ground truth: every defect is planted at a known onset,
so detection latency, false alarms, and sensitivity are measurable exactly. Each SUT answers
a refund-style probe with a JSON payload matching the demo contract's fields. Outputs are
driven by a seeded RNG — stochastic in shape, reproducible by seed.
"""
from __future__ import annotations

import json
import random
import re
from typing import Protocol

from .perturb import sentences


class SUT(Protocol):
    """A system under test: input text + time step -> raw output string."""
    name: str
    def run(self, probe_input: str, t: int, rng: random.Random) -> str: ...


def _payload(decision: str, policies: list[str], wording: str) -> str:
    return json.dumps(
        {"eligibility_decision": decision, "cited_policy_ids": policies,
         "response_wording": wording}
    )


class StableSUT:
    """Healthy process: consistent decision, small harmless wording variation.

    base_flip_p models the residual decision noise every real stochastic process carries;
    the demo default is 0.0 (the shipped demo contract gates at flip 0.01), while the
    golden-defect eval runs the noisy variant so its baseline sigma is realistic."""

    name = "stable"

    def __init__(self, base_flip_p: float = 0.0):
        self.base_flip_p = base_flip_p

    def run(self, probe_input: str, t: int, rng: random.Random) -> str:
        wording = rng.choice([
            "The customer qualifies for a refund under the return policy.",
            "Refund approved per the standard return policy.",
            "This purchase is eligible for a refund.",
        ])
        decision = "eligible"
        if self.base_flip_p and rng.random() < self.base_flip_p:
            decision = "ineligible"
        return _payload(decision, ["POL-7"], wording)


class JumpSUT:
    """Mean shift planted at onset: flip probability jumps from base_flip_p to flip_rate."""

    name = "jump"

    def __init__(self, onset: int, flip_rate: float = 0.35, base_flip_p: float = 0.0):
        self.onset = onset
        self.flip_rate = flip_rate
        self.base_flip_p = base_flip_p

    def run(self, probe_input: str, t: int, rng: random.Random) -> str:
        p = self.flip_rate if t >= self.onset else self.base_flip_p
        decision = "ineligible" if rng.random() < p else "eligible"
        return _payload(decision, ["POL-7"], "Refund decision per policy.")


class DriftSUT:
    """Gradual drift planted at onset: flip probability ramps linearly from base_flip_p
    to base_flip_p + peak over ramp steps."""

    name = "drift"

    def __init__(self, onset: int, peak_flip_rate: float = 0.35, ramp: int = 10,
                 base_flip_p: float = 0.0):
        self.onset = onset
        self.peak = peak_flip_rate
        self.ramp = ramp
        self.base_flip_p = base_flip_p

    def run(self, probe_input: str, t: int, rng: random.Random) -> str:
        p = self.base_flip_p
        if t >= self.onset:
            p = self.base_flip_p + min(1.0, (t - self.onset + 1) / self.ramp) * self.peak
        decision = "ineligible" if rng.random() < p else "eligible"
        return _payload(decision, ["POL-7"], "Refund decision per policy.")


class FlakySUT:
    """Format flake planted at onset: malformed output at rate p during the burst window.
    Decisions carry the same healthy base_flip_p noise as the stable process."""

    name = "flaky"

    def __init__(self, onset: int, p: float = 0.15, burst: int = 15,
                 base_flip_p: float = 0.0):
        self.onset = onset
        self.p = p
        self.burst = burst
        self.base_flip_p = base_flip_p

    def run(self, probe_input: str, t: int, rng: random.Random) -> str:
        if self.onset <= t < self.onset + self.burst and rng.random() < self.p:
            return "Sure! The customer is eligible for a refund :)"   # not JSON: malformed
        decision = "eligible"
        if self.base_flip_p and rng.random() < self.base_flip_p:
            decision = "ineligible"
        return _payload(decision, ["POL-7"], "Refund decision per policy.")


class BimodalSUT:
    """A hidden second outcome mode planted at onset. A fixed share of answers reach the
    SAME decision by a different route: an extra cited policy and a goodwill rationale.
    The decision never flips, so the flip rate stays at zero and the mean Jaccard barely
    moves at a small share; only a view of the outcome distribution shows two modes."""

    name = "bimodal"

    def __init__(self, onset: int, share: float = 0.10):
        self.onset = onset
        self.share = share

    def run(self, probe_input: str, t: int, rng: random.Random) -> str:
        if t >= self.onset and rng.random() < self.share:
            return _payload("eligible", ["POL-7", "POL-12"],
                            "Refund approved as a one-time goodwill exception.")
        return _payload("eligible", ["POL-7"], "Refund approved per the standard return policy.")


_DAYS = re.compile(r"(\d+)\s+days?", re.IGNORECASE)


def _days(probe_input: str) -> int | None:
    match = _DAYS.search(probe_input)
    return int(match.group(1)) if match else None


def _policy_decision(probe_input: str, window: int = 30) -> str:
    days = _days(probe_input)
    return "eligible" if days is None or days <= window else "ineligible"


class PolicySUT:
    """Healthy and input-aware: reads the days since purchase and applies one rule
    (refund inside 30 days). Deterministic, so every invariant holds on it."""

    name = "policy"

    def run(self, probe_input: str, t: int, rng: random.Random) -> str:
        return _payload(_policy_decision(probe_input), ["POL-7"], "Refund decision per policy.")


class DistractibleSUT:
    """Irrelevance defect: an unrelated sentence that mentions a refused refund sways the
    decision, although it says nothing about this customer."""

    name = "distractible"

    def run(self, probe_input: str, t: int, rng: random.Random) -> str:
        swayed = "refused" in probe_input.lower()
        decision = "ineligible" if swayed else _policy_decision(probe_input)
        return _payload(decision, ["POL-7"], "Refund decision per policy.")


class OrderSensitiveSUT:
    """Order defect: it stops reading at the question. Facts stated after the question
    mark are never seen, so the days since purchase are lost and the refund is denied."""

    name = "order-sensitive"

    def run(self, probe_input: str, t: int, rng: random.Random) -> str:
        parts = sentences(probe_input)
        question = next((i for i, s in enumerate(parts) if s.endswith("?")), len(parts))
        read = " ".join(parts[:question + 1])
        facts_lost = _days(probe_input) is not None and _days(read) is None
        decision = "ineligible" if facts_lost else _policy_decision(read)
        return _payload(decision, ["POL-7"], "Refund decision per policy.")


class FormatSensitiveSUT:
    """Format defect: the parser expects sentence case and single spaces. Upper case or
    doubled spaces and the rule is not applied."""

    name = "format-sensitive"

    def run(self, probe_input: str, t: int, rng: random.Random) -> str:
        tidy = probe_input == " ".join(probe_input.split()) and not probe_input.isupper()
        decision = _policy_decision(probe_input) if tidy else "ineligible"
        return _payload(decision, ["POL-7"], "Refund decision per policy.")


class NonMonotonicSUT:
    """Monotonicity defect: the refund window reopens between 45 and 50 days, so an older
    purchase is eligible where a newer one was not."""

    name = "non-monotonic"

    def run(self, probe_input: str, t: int, rng: random.Random) -> str:
        days = _days(probe_input)
        reopened = days is not None and 45 <= days <= 50
        decision = "eligible" if reopened else _policy_decision(probe_input)
        return _payload(decision, ["POL-7"], "Refund decision per policy.")


# Simulators the API and CLI can name. Time-based defects start at run index t = 12 on a
# healthy 4% background flip rate, so a chart has a real baseline before the onset.
DEMO_ONSET = 12
DEMO_BASE_FLIP = 0.04

DEMO_SUTS: dict[str, SUT] = {
    "stable": StableSUT(),
    "noisy": StableSUT(base_flip_p=DEMO_BASE_FLIP),
    "jump": JumpSUT(onset=DEMO_ONSET, base_flip_p=DEMO_BASE_FLIP),
    "drift": DriftSUT(onset=DEMO_ONSET, base_flip_p=DEMO_BASE_FLIP),
    "flaky": FlakySUT(onset=DEMO_ONSET, base_flip_p=DEMO_BASE_FLIP),
    "bimodal": BimodalSUT(onset=DEMO_ONSET),
    "policy": PolicySUT(),
    "distractible": DistractibleSUT(),
    "order-sensitive": OrderSensitiveSUT(),
    "format-sensitive": FormatSensitiveSUT(),
    "non-monotonic": NonMonotonicSUT(),
}

# What each simulator is, in the words the dashboard shows. `planted_defect` is None for a
# healthy process. These are simulators: nothing here is a measurement of a real system.
SUT_CATALOG: dict[str, dict] = {
    "stable": {"summary": "Healthy process. The decision never flips.", "planted_defect": None},
    "noisy": {"summary": "Healthy process with a 4% background flip rate.", "planted_defect": None},
    "jump": {"summary": "Flip rate jumps from 4% to 35% at run 12.",
             "planted_defect": "abrupt mean shift"},
    "drift": {"summary": "Flip rate ramps up over ten runs starting at run 12.",
              "planted_defect": "gradual drift"},
    "flaky": {"summary": "15% of outputs are not valid JSON from run 12 to run 26.",
              "planted_defect": "format flake"},
    "bimodal": {"summary": "From run 12, one answer in ten takes a second route to the same decision.",
                "planted_defect": "hidden second outcome mode"},
    "policy": {"summary": "Healthy and input-aware. Applies a 30 day refund window.",
               "planted_defect": None},
    "distractible": {"summary": "Swayed by an unrelated sentence about a refused refund.",
                     "planted_defect": "irrelevance"},
    "order-sensitive": {"summary": "Reads only the first sentence of the input.",
                        "planted_defect": "order"},
    "format-sensitive": {"summary": "Breaks on upper case or doubled spaces.",
                         "planted_defect": "format"},
    "non-monotonic": {"summary": "The refund window reopens between 45 and 50 days.",
                      "planted_defect": "monotonicity"},
}
