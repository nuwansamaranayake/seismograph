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
    """Healthy process: consistent decision, small harmless wording variation."""

    name = "stable"

    def run(self, probe_input: str, t: int, rng: random.Random) -> str:
        wording = rng.choice([
            "The customer qualifies for a refund under the return policy.",
            "Refund approved per the standard return policy.",
            "This purchase is eligible for a refund.",
        ])
        return _payload("eligible", ["POL-7"], wording)


class JumpSUT:
    """Mean shift planted at onset: after t >= onset, decisions flip at flip_rate."""

    name = "jump"

    def __init__(self, onset: int, flip_rate: float = 0.35):
        self.onset = onset
        self.flip_rate = flip_rate

    def run(self, probe_input: str, t: int, rng: random.Random) -> str:
        decision = "eligible"
        if t >= self.onset and rng.random() < self.flip_rate:
            decision = "ineligible"
        return _payload(decision, ["POL-7"], "Refund decision per policy.")


class DriftSUT:
    """Gradual drift planted at onset: flip probability ramps linearly to peak over ramp steps."""

    name = "drift"

    def __init__(self, onset: int, peak_flip_rate: float = 0.35, ramp: int = 10):
        self.onset = onset
        self.peak = peak_flip_rate
        self.ramp = ramp

    def run(self, probe_input: str, t: int, rng: random.Random) -> str:
        decision = "eligible"
        if t >= self.onset:
            level = min(1.0, (t - self.onset + 1) / self.ramp) * self.peak
            if rng.random() < level:
                decision = "ineligible"
        return _payload(decision, ["POL-7"], "Refund decision per policy.")


class FlakySUT:
    """Format flake planted at onset: malformed output at rate p during the burst window."""

    name = "flaky"

    def __init__(self, onset: int, p: float = 0.15, burst: int = 15):
        self.onset = onset
        self.p = p
        self.burst = burst

    def run(self, probe_input: str, t: int, rng: random.Random) -> str:
        if self.onset <= t < self.onset + self.burst and rng.random() < self.p:
            return "Sure! The customer is eligible for a refund :)"   # not JSON: malformed
        return _payload("eligible", ["POL-7"], "Refund decision per policy.")


DEMO_SUTS: dict[str, SUT] = {"stable": StableSUT()}
