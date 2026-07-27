"""Synthetic systems under test with programmable defects.

These are the golden-defect suite's ground truth: every defect is planted at a known onset,
so detection latency, false alarms, and sensitivity are measurable exactly. Each SUT answers
a refund-style probe with a JSON payload matching the demo contract's fields. Outputs are
driven by a seeded RNG — stochastic in shape, reproducible by seed.
"""
from __future__ import annotations

import json
import random
from typing import Protocol


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


DEMO_SUTS: dict[str, SUT] = {"stable": StableSUT()}
