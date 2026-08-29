"""Compatibility exports for the durable local job vocabulary."""

from __future__ import annotations

from rflp_lite.ports.jobs import (
    ACTIVE_JOB_STATUSES,
    TERMINAL_JOB_STATUSES,
    JobStatus,
)

__all__ = ["ACTIVE_JOB_STATUSES", "JobStatus", "TERMINAL_JOB_STATUSES"]
