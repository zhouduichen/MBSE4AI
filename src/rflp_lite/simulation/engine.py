from __future__ import annotations

import heapq

from rflp_lite.domain.canonical import canonical_hash
from rflp_lite.domain.models import Candidate, SimulationEvent, SimulationRun


def simulate(candidate: Candidate, seed: int) -> SimulationRun:
    scheduled = [
        (0, 10, 0, "create", "content", (("version", "v1"),)),
        (1, 10, 1, "retrieve", "content", (("version", "v1"),)),
        (2, 5, 2, "restore", "content", (("version", "v1"), ("fault", "retry-once"))),
        (3, 10, 3, "audit", "audit-log", (("action", "restore"),)),
    ]
    heapq.heapify(scheduled)
    events: list[SimulationEvent] = []
    while scheduled:
        time, priority, sequence, kind, target, payload = heapq.heappop(scheduled)
        events.append(SimulationEvent(time, priority, sequence, kind, target, payload))
    latency_ms = 18 + (seed % 5) + (0 if candidate.pattern == "ports-adapters" else 4)
    metrics = (
        ("latency_ms", latency_ms),
        ("capacity_versions", 100),
        ("failure_recovered", 1),
        ("audit_events", 1),
    )
    passed = latency_ms <= 30 and len(events) == 4 and events[-1].kind == "audit"
    trace_hash = canonical_hash((candidate.id, seed, tuple(events), metrics, passed))
    return SimulationRun(
        id=f"simulation-{trace_hash[:12]}",
        candidate_id=candidate.id,
        events=tuple(events),
        metrics=metrics,
        passed=passed,
        trace_hash=trace_hash,
    )

