"""Pure, persistence-free merge dispatch for validated analysis blocks."""

from rflp_lite.application.intelligence.merge.registry import MERGERS, dispatch_merge

__all__ = ["MERGERS", "dispatch_merge"]
