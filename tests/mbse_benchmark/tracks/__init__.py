"""Explicit benchmark tracks; never merge their scores into one number."""

from __future__ import annotations

from enum import StrEnum


class BenchmarkTrack(StrEnum):
    HARNESS = "harness"
    LLM = "llm"
    ROBUSTNESS = "robustness"


__all__ = ["BenchmarkTrack"]
