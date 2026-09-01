"""Pure, persistence-free merge dispatch for validated analysis blocks."""

from rflp_lite.application.intelligence.merge.registry import ALL_MERGERS, MERGERS, dispatch_merge

__all__ = ["MERGERS", "ALL_MERGERS", "dispatch_merge"]
