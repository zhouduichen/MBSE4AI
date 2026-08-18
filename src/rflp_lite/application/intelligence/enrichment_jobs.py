"""Local, durable, block-level LLM enrichment for the requirements workbench."""

from __future__ import annotations

import time
import threading
from pathlib import Path
from typing import Any

from rflp_lite.application.dependencies import ApplicationDependencies, require_dependencies
from rflp_lite.application.intelligence.analysis_blocks import (
    build_analysis_blocks,
    build_block_request,
    merge_block_result,
)
from rflp_lite.application.intelligence.pack_composition import compose_pack_selection
from rflp_lite.domain.canonical import canonical_hash, canonical_json
from rflp_lite.domain.errors import AdapterFailure, ContractViolation, InvariantViolation
from rflp_lite.ports.generative_model import GenerativeModel


_TERMINAL_BLOCKS = {"succeeded", "failed", "degraded"}


def _clone(value: object) -> object:
    import json

    return json.loads(canonical_json(value))


def _block_ids(blocks: object) -> list[str]:
    if not isinstance(blocks, (list, tuple)):
        return []
    result = []
    for block in blocks:
        block_id = str(getattr(block, "id", "") or "")
        if block_id and block_id not in result:
            result.append(block_id)
    return result


class EnrichmentJobRunner:
    """Run each analysis block independently while retaining completed work."""

    def __init__(
        self,
        workspace_path: Path,
        *,
        dependencies: ApplicationDependencies | None = None,
        job_service: Any | None = None,
    ):
        self.workspace_path = Path(workspace_path)
        self.dependencies = require_dependencies(dependencies)
        self.jobs = job_service or self.dependencies.job_service_factory(self.workspace_path)

    def _load_state(self) -> dict[str, object]:
        repository = self.dependencies.repository_factory(self.workspace_path / ".rflp" / "model.db")
        try:
            state = repository.load_workbench()
        finally:
            repository.close()
        if not isinstance(state, dict):
            raise ContractViolation("requirements workbench is empty")
        return state

    @staticmethod
    def _input_hash(state: dict[str, object]) -> str:
        scope = state.get("project_scope")
        if isinstance(scope, dict) and str(scope.get("input_hash", "")):
            return str(scope["input_hash"])
        return canonical_hash(state.get("document_regions", state.get("spans", [])))

    def _save_state(self, state: dict[str, object], block_id: str) -> dict[str, object]:
        repository = self.dependencies.repository_factory(self.workspace_path / ".rflp" / "model.db")
        try:
            with repository.transaction():
                repository.save_workbench(state, f"requirements.enrichment.{block_id}")
        finally:
            repository.close()
        return state

    def _execute(
        self,
        job_id: str,
        model: GenerativeModel | None,
        expected_input_hash: str | None,
        previous_blocks: dict[str, object] | None = None,
    ) -> dict[str, object]:
        state = self._load_state()
        input_hash = self._input_hash(state)
        if expected_input_hash and expected_input_hash != input_hash:
            raise ContractViolation("需求输入已变化，旧的增量任务不能继续合并")
        pack = compose_pack_selection(state.get("analysis_config") or {})
        blocks = build_analysis_blocks(state, pack)
        block_map = {str(getattr(block, "id")): block for block in blocks}
        statuses = {
            block_id: str((previous_blocks or {}).get(block_id, "queued"))
            for block_id in block_map
        }
        self.jobs.update(
            job_id,
            {
                "status": "running",
                "input_hash": input_hash,
                "pack_ids": pack.get("pack_ids", []),
                "pack_hashes": pack.get("pack_hashes", {}),
                "blocks": statuses,
                "model": getattr(model, "model_id", "") or "local-profile",
                "retryable": True,
            },
        )
        if model is None:
            for block_id in statuses:
                statuses[block_id] = "failed"
            state.setdefault("auto_analysis", {})
            state["auto_analysis"].update(
                {
                    "status": "degraded",
                    "diagnostics": [
                        {
                            "code": "generative_model_unavailable",
                            "severity": "warning",
                            "message": "当前未配置可用 LLM，已保留 accepted 基线。",
                        }
                    ],
                }
            )
            self._save_state(state, "baseline")
            self.jobs.update(job_id, {"status": "degraded", "blocks": statuses})
            return {"status": "degraded", "merged_item_ids": [], "blocks": statuses}

        merged_ids: list[str] = []
        diagnostics: list[dict[str, object]] = []
        for block_id, block in block_map.items():
            if statuses[block_id] == "succeeded":
                continue
            started = time.monotonic()
            statuses[block_id] = "running"
            self.jobs.update(
                job_id,
                {"status": "running", "blocks": statuses, "active_block": block_id},
            )
            try:
                request = build_block_request(state, block, pack)
                response = model.complete_json(request)
                before = {
                    str(item.get("id"))
                    for group in ("claims", "structured_requirements", "stakeholders", "concerns", "needs", "scenarios")
                    for item in state.get(group, ())
                    if isinstance(item, dict) and item.get("id")
                }
                state = merge_block_result(state, block_id, response)
                after = {
                    str(item.get("id"))
                    for group in ("claims", "structured_requirements", "stakeholders", "concerns", "needs", "scenarios")
                    for item in state.get(group, ())
                    if isinstance(item, dict) and item.get("id")
                }
                merged_ids.extend(sorted(after - before))
                statuses[block_id] = "succeeded"
            except AdapterFailure as exc:
                statuses[block_id] = "failed"
                diagnostics.append({"code": "llm_block_failed", "block_id": block_id, "message": str(exc)})
            except (ContractViolation, ValueError, TypeError) as exc:
                statuses[block_id] = "degraded"
                diagnostics.append({"code": "llm_block_degraded", "block_id": block_id, "message": str(exc)})
            finally:
                self.jobs.update(
                    job_id,
                    {
                        "blocks": statuses,
                        "block_durations_ms": {
                            **(
                                self.jobs.get(job_id) or {}
                            ).get("block_durations_ms", {}),
                            block_id: max(0, int((time.monotonic() - started) * 1000)),
                        },
                    },
                )
            if statuses[block_id] == "succeeded":
                self._save_state(state, block_id)

        terminal = set(statuses.values())
        status = "completed" if terminal == {"succeeded"} else "degraded"
        if status == "completed":
            try:
                from rflp_lite.application.requirements_workbench import generate_model
                from rflp_lite.application.mbse_modeling import generate_mbse_revision

                state = generate_model(state)
                state = generate_mbse_revision(state)
            except (ContractViolation, InvariantViolation, ValueError, TypeError, KeyError):
                # A partial architectural graph must not erase the accepted
                # baseline or turn an otherwise useful enrichment job into a
                # transport failure.
                diagnostics.append(
                    {
                        "code": "derived_model_deferred",
                        "severity": "warning",
                        "message": "分块结果已保存，正式 RFLP 仍需在需求检查页生成。",
                    }
                )
        analysis = dict(state.get("auto_analysis") or {})
        analysis.update(
            {
                "status": status,
                "job_id": job_id,
                "input_hash": input_hash,
                "blocks": statuses,
                "diagnostics": diagnostics[-12:],
            }
        )
        state["auto_analysis"] = analysis
        self._save_state(state, "final")
        self.jobs.update(
            job_id,
            {
                "status": status,
                "blocks": statuses,
                "merged_item_ids": sorted(set(merged_ids)),
                "error": diagnostics[-1] if diagnostics else None,
                "retryable": status != "completed",
            },
        )
        return {
            "status": status,
            "blocks": statuses,
            "merged_item_ids": sorted(set(merged_ids)),
            "diagnostics": diagnostics,
        }

    def submit(
        self,
        model: GenerativeModel | None,
        *,
        input_hash: str | None = None,
        previous_blocks: dict[str, object] | None = None,
    ) -> dict[str, object]:
        state = self._load_state()
        current_hash = self._input_hash(state)
        expected = input_hash or current_hash
        pack = compose_pack_selection(state.get("analysis_config") or {})
        blocks = build_analysis_blocks(state, pack)
        payload = {
            "workspace": self.workspace_path.name,
            "input_hash": expected,
            "pack_ids": pack.get("pack_ids", []),
            "blocks": {block_id: "queued" for block_id in _block_ids(blocks)},
        }
        if previous_blocks:
            payload["blocks"] = dict(previous_blocks)
        holder: dict[str, str] = {}
        ready = threading.Event()

        def execute() -> dict[str, object]:
            ready.wait(timeout=10)
            return self._execute(
                holder["id"],
                model,
                expected,
                previous_blocks,
            )

        record = self.jobs.submit_async(
            "requirements.enrichment",
            payload,
            execute,
        )
        holder["id"] = str(record["id"])
        ready.set()
        return record

    def run(
        self, model: GenerativeModel | None, *, input_hash: str | None = None
    ) -> dict[str, object]:
        """Submit and wait; useful for deterministic application-level tests."""

        record = self.submit(model, input_hash=input_hash)
        job_id = str(record["id"])
        for _ in range(600):
            current = self.jobs.get(job_id)
            if current and current.get("status") in {"succeeded", "completed", "failed", "degraded"}:
                return current
            time.sleep(0.05)
        raise TimeoutError("enrichment job did not finish")

    def retry(self, job_id: str, model: GenerativeModel | None) -> dict[str, object]:
        previous = self.jobs.get(job_id)
        if previous is None:
            raise ContractViolation("enrichment job not found")
        blocks = previous.get("blocks") if isinstance(previous.get("blocks"), dict) else {}
        return self.submit(
            model,
            input_hash=str(previous.get("input_hash", "")) or None,
            previous_blocks={key: value for key, value in blocks.items() if value == "succeeded"},
        )


def submit_requirement_enrichment(
    workspace_name: str,
    input_hash: str,
    workspace_root: Path,
    model: GenerativeModel | None,
) -> dict[str, object]:
    return EnrichmentJobRunner(workspace_root / workspace_name).submit(
        model, input_hash=input_hash
    )


__all__ = ["EnrichmentJobRunner", "submit_requirement_enrichment"]
