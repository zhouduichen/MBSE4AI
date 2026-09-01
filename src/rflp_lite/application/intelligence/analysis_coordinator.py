"""Minimal durable parent/child orchestration for requirements analysis."""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any

from rflp_lite.application.dependencies import ApplicationDependencies, configured_dependencies
from rflp_lite.domain.canonical import canonical_hash
from rflp_lite.domain.errors import ContractViolation
from rflp_lite.ports.generative_model import GenerativeModel


BLOCK_IDS = (
    "system_scope",
    "stakeholders",
    "concerns_needs",
    "requirements",
    "scenarios",
    "architecture",
)
PARENT_KIND = "requirements.analysis"
CHILD_KIND = "requirements.analysis.block"
RETRYABLE_STATUSES = frozenset({"failed", "degraded", "interrupted"})


class _Heartbeat:
    def __init__(self, jobs: Any, job_id: str):
        self.jobs = jobs
        self.job_id = job_id
        self.stop = threading.Event()
        self.thread: threading.Thread | None = None

    def __enter__(self) -> "_Heartbeat":
        if not hasattr(self.jobs, "heartbeat"):
            return self
        lease_seconds = float(getattr(self.jobs, "lease_seconds", 30.0) or 30.0)
        interval = max(0.1, min(5.0, lease_seconds / 3.0))

        def keep_alive() -> None:
            while not self.stop.wait(interval):
                current = self.jobs.get(self.job_id) or {}
                lease_id = str(current.get("lease_id", ""))
                if not lease_id or self.jobs.heartbeat(self.job_id, lease_id) is None:
                    return

        self.thread = threading.Thread(
            target=keep_alive,
            name=f"rflp-parent-lease-{self.job_id}",
            daemon=True,
        )
        self.thread.start()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.stop.set()
        if self.thread is not None:
            self.thread.join(timeout=1.0)


class AnalysisCoordinator:
    """Create one parent run and execute its selected blocks serially."""

    def __init__(
        self,
        workspace_path: Path,
        *,
        dependencies: ApplicationDependencies | None = None,
        job_service: Any | None = None,
        runner: Any | None = None,
    ) -> None:
        self.workspace_path = Path(workspace_path)
        self.dependencies = configured_dependencies(dependencies)
        self.jobs = job_service or self.dependencies.job_service_factory(self.workspace_path)
        self._runner_instance = runner

    def _runner(self) -> Any:
        if self._runner_instance is None:
            raise ContractViolation(
                "AnalysisCoordinator 需要注入 EnrichmentJobRunner"
            )
        return self._runner_instance

    def _queued_submit(self, kind: str, payload: dict[str, object]) -> dict[str, object]:
        repository = getattr(self.jobs, "_repository", None)
        if repository is None or not hasattr(repository, "submit"):
            raise ContractViolation("AnalysisCoordinator 需要支持 SQLite JobRepository 的 JobService")
        return repository.submit(kind, payload)

    @staticmethod
    def _public_status(statuses: dict[str, str]) -> str:
        values = set(statuses.values())
        if "superseded" in values:
            return "superseded"
        if "interrupted" in values:
            return "interrupted"
        if values == {"succeeded"}:
            return "completed"
        if values and values <= {"failed"}:
            # A parent run is a partial-analysis container.  Even when every
            # child provider call fails, the accepted baseline remains valid
            # and the UI should offer block-level retry instead of presenting
            # the whole analysis as an unrecoverable job failure.
            return "degraded"
        return "degraded"

    def _child_payload(
        self,
        parent_id: str,
        block_id: str,
        *,
        input_hash: str,
        mode: str,
        delta_region_ids: tuple[str, ...],
        snapshot_revision: int,
        snapshot_content_revision: int,
        analysis_config_hash: str,
    ) -> dict[str, object]:
        key = canonical_hash(
            (
                self.workspace_path.resolve().as_posix(),
                parent_id,
                block_id,
                input_hash,
                mode,
                snapshot_content_revision,
                analysis_config_hash,
                1,
            )
        )
        return {
            "workspace": self.workspace_path.name,
            "parent_job_id": parent_id,
            "block_id": block_id,
            "input_hash": input_hash,
            "content_revision": snapshot_content_revision,
            "mode": mode,
            "analysis_mode": mode,
            "delta_region_ids": list(delta_region_ids),
            "snapshot_revision": snapshot_revision,
            "snapshot_content_revision": snapshot_content_revision,
            "analysis_config_hash": analysis_config_hash,
            "batch_index": 1,
            "idempotency_key": f"requirements.analysis.block:{key}",
            "blocks": {block_id: "queued"},
        }

    def _create_parent(
        self,
        model: GenerativeModel | None,
        *,
        input_hash: str,
        mode: str,
        delta_region_ids: tuple[str, ...],
        snapshot_revision: int,
        snapshot_content_revision: int,
        analysis_config_hash: str,
        idempotency_key: str | None,
        selected_blocks: tuple[str, ...],
        inherited_blocks: dict[str, str] | None = None,
    ) -> dict[str, object]:
        statuses = {
            block_id: (inherited_blocks or {}).get(block_id, "queued")
            for block_id in BLOCK_IDS
        }
        parent_key = idempotency_key or canonical_hash(
            (
                self.workspace_path.resolve().as_posix(),
                input_hash,
                mode,
                snapshot_content_revision,
                analysis_config_hash,
                tuple(selected_blocks),
            )
        )
        payload: dict[str, object] = {
            "workspace": self.workspace_path.name,
            "input_hash": input_hash,
            "mode": mode,
            "analysis_mode": mode,
            "delta_region_ids": list(delta_region_ids),
            "snapshot_revision": snapshot_revision,
            "snapshot_content_revision": snapshot_content_revision,
            "content_revision": snapshot_content_revision,
            "analysis_config_hash": analysis_config_hash,
            "selected_block_ids": list(selected_blocks),
            "blocks": statuses,
            "idempotency_key": f"requirements.analysis:{parent_key}",
        }
        gate = threading.Event()
        holder: dict[str, str] = {}

        def execute() -> dict[str, object]:
            gate.wait(timeout=10)
            return self._run_parent(holder["id"], model)

        existing = next(
            (
                item
                for item in self.jobs.list()
                if str(item.get("idempotency_key", "")) == str(payload["idempotency_key"])
                and str(item.get("status")) in {"queued", "running"}
            ),
            None,
        )
        if existing is not None:
            return existing
        record = self.jobs.submit_async(PARENT_KIND, payload, execute)
        parent_id = str(record["id"])
        holder["id"] = parent_id

        child_ids: list[str] = []
        for block_id in selected_blocks:
            child = self._queued_submit(
                CHILD_KIND,
                self._child_payload(
                    parent_id,
                    block_id,
                    input_hash=input_hash,
                    mode=mode,
                    delta_region_ids=delta_region_ids,
                    snapshot_revision=snapshot_revision,
                    snapshot_content_revision=snapshot_content_revision,
                    analysis_config_hash=analysis_config_hash,
                ),
            )
            child_ids.append(str(child["id"]))
        self.jobs.update(
            parent_id,
            {
                "child_job_ids": child_ids,
                "selected_block_ids": list(selected_blocks),
                "blocks": statuses,
                "block_states": statuses,
            },
        )
        gate.set()
        return self.jobs.get(parent_id) or record

    def submit(
        self,
        model: GenerativeModel | None,
        input_hash: str,
        mode: str = "incremental",
        delta_region_ids: tuple[str, ...] = (),
        snapshot_revision: int = 0,
        snapshot_content_revision: int = 0,
        analysis_config_hash: str = "",
        idempotency_key: str | None = None,
    ) -> dict[str, object]:
        return self._create_parent(
            model,
            input_hash=input_hash,
            mode=mode,
            delta_region_ids=delta_region_ids,
            snapshot_revision=snapshot_revision,
            snapshot_content_revision=snapshot_content_revision,
            analysis_config_hash=analysis_config_hash,
            idempotency_key=idempotency_key,
            selected_blocks=BLOCK_IDS,
        )

    def _run_parent(self, parent_id: str, model: GenerativeModel | None) -> dict[str, object]:
        parent = self.jobs.get(parent_id) or {}
        payload = parent.get("payload") if isinstance(parent.get("payload"), dict) else {}
        selected = tuple(
            str(value)
            for value in payload.get("selected_block_ids", BLOCK_IDS)
            if str(value) in BLOCK_IDS
        )
        statuses = {
            block_id: str((payload.get("blocks") or {}).get(block_id, "queued"))
            for block_id in BLOCK_IDS
        }
        child_ids = [str(value) for value in parent.get("child_job_ids", ())]
        diagnostics: list[dict[str, object]] = []
        runner = self._runner()
        with _Heartbeat(self.jobs, parent_id):
            for block_id, child_id in zip(selected, child_ids):
                statuses[block_id] = "running"
                self.jobs.update(
                    parent_id,
                    {
                        "status": "running",
                        "active_block": block_id,
                        "blocks": statuses,
                        "block_states": statuses,
                    },
                )
                child_payload = (self.jobs.get(child_id) or {}).get("payload", {})
                try:
                    child = self.jobs.submit(
                        CHILD_KIND,
                        child_payload if isinstance(child_payload, dict) else {},
                        lambda child_id=child_id, block_id=block_id: runner._execute_block_job(
                            child_id, model, block_id
                        ),
                    )
                except Exception as exc:
                    child = self.jobs.get(child_id) or {}
                    statuses[block_id] = "failed"
                    diagnostics.append(
                        {
                            "code": "child_job_failed",
                            "block_id": block_id,
                            "message": str(exc),
                        }
                    )
                else:
                    statuses[block_id] = str(child.get("status", "failed"))
                    child_diagnostics = child.get("diagnostics")
                    if isinstance(child_diagnostics, list):
                        diagnostics.extend(
                            {"block_id": block_id, **item}
                            for item in child_diagnostics
                            if isinstance(item, dict)
                        )
                self.jobs.update(
                    parent_id,
                    {
                        "blocks": statuses,
                        "block_states": statuses,
                        "child_job_ids": child_ids,
                        "completed_blocks": [
                            key for key, value in statuses.items() if value == "succeeded"
                        ],
                    },
                )
        status = self._public_status(statuses)
        final_status = runner._finalize_coordinated_run(
            parent_id,
            status=status,
            statuses=statuses,
            diagnostics=diagnostics,
            expected_content_revision=int(payload.get("content_revision", 0) or 0),
        )
        if final_status != status:
            status = final_status
        return {
            "status": status,
            "blocks": statuses,
            "child_job_ids": child_ids,
            "diagnostics": diagnostics,
        }

    def retry_failed(self, parent_job_id: str, model: GenerativeModel | None) -> dict[str, object]:
        previous = self.jobs.get(parent_job_id)
        if previous is None:
            raise ContractViolation("analysis parent Job not found")
        if str(previous.get("kind")) != PARENT_KIND:
            raise ContractViolation("只能重试 requirements.analysis 父 Job")
        if str(previous.get("status")) not in RETRYABLE_STATUSES:
            raise ContractViolation("只有 failed、degraded 或 interrupted 父 Job 可以重试")
        statuses = previous.get("blocks") if isinstance(previous.get("blocks"), dict) else {}
        selected = tuple(
            block_id for block_id in BLOCK_IDS if str(statuses.get(block_id)) in RETRYABLE_STATUSES
        )
        if not selected:
            raise ContractViolation("没有需要重试的失败分析块")
        payload = previous.get("payload") if isinstance(previous.get("payload"), dict) else {}
        inherited = {block_id: "succeeded" for block_id in BLOCK_IDS if statuses.get(block_id) == "succeeded"}
        return self._create_parent(
            model,
            input_hash=str(payload.get("input_hash", "")),
            mode=str(payload.get("mode", "incremental")),
            delta_region_ids=tuple(str(value) for value in payload.get("delta_region_ids", ()) if str(value)),
            snapshot_revision=int(payload.get("snapshot_revision", 0) or 0),
            snapshot_content_revision=int(payload.get("content_revision", 0) or 0),
            analysis_config_hash=str(payload.get("analysis_config_hash", "")),
            idempotency_key=None,
            selected_blocks=selected,
            inherited_blocks=inherited,
        )

    def submit_block(
        self,
        block_id: str,
        model: GenerativeModel | None,
        *,
        input_hash: str,
        mode: str = "incremental",
        delta_region_ids: tuple[str, ...] = (),
        snapshot_revision: int = 0,
        snapshot_content_revision: int = 0,
        analysis_config_hash: str = "",
        parent_job_id: str | None = None,
    ) -> dict[str, object]:
        if block_id not in BLOCK_IDS:
            raise ContractViolation(f"未知分析块: {block_id}")
        if parent_job_id:
            payload = self._child_payload(
                parent_job_id,
                block_id,
                input_hash=input_hash,
                mode=mode,
                delta_region_ids=delta_region_ids,
                snapshot_revision=snapshot_revision,
                snapshot_content_revision=snapshot_content_revision,
                analysis_config_hash=analysis_config_hash,
            )
            return self._queued_submit(CHILD_KIND, payload)
        return self._create_parent(
            model,
            input_hash=input_hash,
            mode=mode,
            delta_region_ids=delta_region_ids,
            snapshot_revision=snapshot_revision,
            snapshot_content_revision=snapshot_content_revision,
            analysis_config_hash=analysis_config_hash,
            idempotency_key=None,
            selected_blocks=(block_id,),
        )

    def retry_block(self, parent_job_id: str, block_id: str, model: GenerativeModel | None) -> dict[str, object]:
        previous = self.jobs.get(parent_job_id)
        if previous is None:
            raise ContractViolation("analysis parent Job not found")
        statuses = previous.get("blocks") if isinstance(previous.get("blocks"), dict) else {}
        if str(statuses.get(block_id)) not in RETRYABLE_STATUSES:
            raise ContractViolation("成功分析块不需要重试")
        payload = previous.get("payload") if isinstance(previous.get("payload"), dict) else {}
        inherited = {key: "succeeded" for key, value in statuses.items() if value == "succeeded"}
        return self._create_parent(
            model,
            input_hash=str(payload.get("input_hash", "")),
            mode=str(payload.get("mode", "incremental")),
            delta_region_ids=tuple(str(value) for value in payload.get("delta_region_ids", ()) if str(value)),
            snapshot_revision=int(payload.get("snapshot_revision", 0) or 0),
            snapshot_content_revision=int(payload.get("content_revision", 0) or 0),
            analysis_config_hash=str(payload.get("analysis_config_hash", "")),
            idempotency_key=None,
            selected_blocks=(block_id,),
            inherited_blocks=inherited,
        )


__all__ = ["AnalysisCoordinator", "BLOCK_IDS", "CHILD_KIND", "PARENT_KIND"]
