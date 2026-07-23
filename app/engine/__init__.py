"""Seismograph engine: deterministic core.

Contracts compile to plans, samplers collect distributions, canonicalization reduces them to
metrics, control charts turn metrics into signals. The only non-deterministic parts of the
system (the SUT itself, LLM variant generation) live behind explicit seams.
"""
