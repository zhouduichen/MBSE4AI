"""Composable orchestration for snapshot-bound enrichment jobs."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass

from rflp_lite.domain.canonical import canonical_hash


@dataclass(frozen=True, slots=True)
class EnrichmentSnapshot:
    revision: int
    content_revision: int
    input_hash: str


class SnapshotGuard:
    def matches(self, current: Mapping[str, object], snapshot: EnrichmentSnapshot) -> bool:
        scope = current.get("project_scope")
        scope = scope if isinstance(scope, Mapping) else {}
        return (
            int(current.get("content_revision", current.get("revision", 0)) or 0)
            == snapshot.content_revision
            and str(scope.get("input_hash", "")) == snapshot.input_hash
        )


class BatchPlanner:
    def plan(self, block_ids: Iterable[str], completed: Iterable[str] = ()) -> tuple[str, ...]:
        completed_set = {str(item) for item in completed}
        return tuple(dict.fromkeys(str(item) for item in block_ids if str(item) not in completed_set))


class BlockExecutor:
    def execute(self, block_id: str) -> object:
        raise NotImplementedError


class BlockCommitter:
    def commit(self, block_id: str, result: object) -> object:
        raise NotImplementedError


class ProgressReporter:
    def report(self, block_id: str, status: str, diagnostics: tuple[Mapping[str, object], ...] = ()) -> None:
        del block_id, status, diagnostics


class Finalizer:
    def finalize(self, results: Mapping[str, object]) -> dict[str, object]:
        return {
            "status": "succeeded" if all(value is not None for value in results.values()) else "degraded",
            "results": dict(results),
            "result_hash": canonical_hash(results),
        }


@dataclass(slots=True)
class EnrichmentCoordinator:
    """Run independent blocks with resumable successful-block semantics."""

    guard: SnapshotGuard
    planner: BatchPlanner
    executor: BlockExecutor
    committer: BlockCommitter
    progress: ProgressReporter
    finalizer: Finalizer

    def run(
        self,
        current: Mapping[str, object],
        snapshot: EnrichmentSnapshot,
        block_ids: Iterable[str],
        *,
        completed: Iterable[str] = (),
    ) -> dict[str, object]:
        if not self.guard.matches(current, snapshot):
            return {
                "status": "superseded",
                "results": {},
                "diagnostics": ({"code": "snapshot_stale"},),
            }
        results: dict[str, object] = {}
        failures: list[dict[str, object]] = []
        for block_id in self.planner.plan(block_ids, completed):
            self.progress.report(block_id, "running")
            try:
                value = self.executor.execute(block_id)
                results[block_id] = self.committer.commit(block_id, value)
            except Exception as exc:  # one failed block must not erase completed blocks
                diagnostic = {"block_id": block_id, "type": type(exc).__name__, "message": str(exc)}
                failures.append(diagnostic)
                self.progress.report(block_id, "failed", (diagnostic,))
                continue
            self.progress.report(block_id, "succeeded")
        final = self.finalizer.finalize(results)
        if failures:
            final["status"] = "degraded" if results else "failed"
            final["diagnostics"] = tuple(failures)
        return final
