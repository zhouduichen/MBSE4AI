"""Local, durable, block-level LLM enrichment for the requirements workbench."""

from __future__ import annotations

import time
import threading
import uuid
from dataclasses import replace
from pathlib import Path
from typing import Any

from rflp_lite.application.dependencies import ApplicationDependencies, configured_dependencies
from rflp_lite.application.intelligence.analysis_blocks import (
    build_analysis_blocks,
    build_block_request,
    merge_block_result,
)
from rflp_lite.application.intelligence.semantic_validator import AnalysisSemanticValidator
from rflp_lite.application.intelligence.validated_result import validate_and_build_result
from rflp_lite.application.intelligence.pack_composition import compose_pack_selection
from rflp_lite.application.intelligence.project_snapshot import (
    build_project_snapshot,
    source_batches,
)
from rflp_lite.application.intelligence.source_references import (
    allowed_source_region_ids,
    repair_source_region_ids,
)
from rflp_lite.application.intelligence.coverage_audit import evaluate_project_coverage
from rflp_lite.application.project_scope import validate_project_references
from rflp_lite.domain.canonical import canonical_hash, canonical_json
from rflp_lite.domain.errors import AdapterFailure, ContractViolation, InvariantViolation
from rflp_lite.ports.generative_model import GenerativeModel


_TERMINAL_BLOCKS = {"succeeded", "failed", "degraded", "interrupted", "superseded"}
_ENRICHMENT_JOB_KINDS = frozenset({"requirements.enrichment", "enrichment"})
_RETRYABLE_JOB_STATUSES = frozenset({"failed", "degraded", "interrupted"})


class _LeaseHeartbeat:
    """Keep a local job lease alive while a provider is generating output."""

    def __init__(self, runner: "EnrichmentJobRunner", job_id: str):
        self.runner = runner
        self.job_id = job_id
        self.stop = threading.Event()
        self.thread: threading.Thread | None = None

    def __enter__(self) -> "_LeaseHeartbeat":
        if not hasattr(self.runner.jobs, "heartbeat"):
            return self
        lease_seconds = float(getattr(self.runner.jobs, "lease_seconds", 30.0) or 30.0)
        interval = max(0.1, min(5.0, lease_seconds / 3.0))

        def keep_alive() -> None:
            while not self.stop.wait(interval):
                if not self.runner._heartbeat(self.job_id):
                    return

        self.thread = threading.Thread(
            target=keep_alive,
            name=f"rflp-lease-{self.job_id}",
            daemon=True,
        )
        self.thread.start()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.stop.set()
        if self.thread is not None:
            self.thread.join(timeout=1.0)


def _legacy_fixture_response(response: Any, block_id: str, state: dict[str, object]) -> Any:
    """Adapt pre-v2 in-process fake models during the compatibility window.

    Real provider responses carry ``provider_id``/``model_id`` and are never
    adapted.  This keeps the repository's deterministic fixtures usable while
    the strict v2 contract is rolled through the test doubles and callers.
    """

    if getattr(response, "provider_id", "") or getattr(response, "model_id", ""):
        return response
    payload = response.payload if isinstance(response.payload, dict) else {}
    regions = state.get("document_regions") or state.get("spans") or []
    source_region_ids = [
        str(item.get("id"))
        for item in regions[:1]
        if isinstance(item, dict) and item.get("id")
    ]
    raw_items = payload.get("items") if isinstance(payload.get("items"), list) else []
    if not raw_items:
        if block_id == "system_scope" and isinstance(payload.get("system"), dict):
            raw_items = [payload["system"]]
        elif block_id in {"stakeholders", "requirements", "scenarios"}:
            legacy_key = {
                "stakeholders": "stakeholders",
                "requirements": "requirements",
                "scenarios": "scenarios",
            }[block_id]
            raw_items = payload.get(legacy_key, []) if isinstance(payload.get(legacy_key), list) else []
        elif block_id == "concerns_needs":
            raw_items = []
            raw_items.extend(
                {**item, "kind": "concern"}
                for item in payload.get("concerns", [])
                if isinstance(item, dict)
            )
            raw_items.extend(
                {**item, "kind": "need"}
                for item in payload.get("needs", [])
                if isinstance(item, dict)
            )
        elif block_id == "architecture" and isinstance(payload.get("architecture"), dict):
            architecture = payload["architecture"]
            raw_items = []
            for key, kind in (
                ("functions", "function"),
                ("logical_components", "logical_component"),
                ("physical_components", "physical_component"),
                ("interfaces", "interface"),
            ):
                raw_items.extend(
                    {**item, "kind": kind}
                    for item in architecture.get(key, [])
                    if isinstance(item, dict)
                )
            raw_items.extend(
                {**item, "kind": "relation"}
                for item in architecture.get("relations", [])
                if isinstance(item, dict)
            )
    normalized_items: list[dict[str, object]] = []
    for raw in raw_items:
        if not isinstance(raw, dict):
            continue
        item = dict(raw)
        item.setdefault("id", f"{block_id}-{len(normalized_items) + 1}")
        item.setdefault("source_region_ids", source_region_ids)
        item.setdefault("confidence", 0.7)
        if block_id == "stakeholders":
            item.setdefault("goals", [])
            item.setdefault("interactions", [])
        elif block_id == "requirements":
            item.setdefault("subject", "系统")
            item.setdefault("predicate", "应")
            item.setdefault("verification_method", "analysis")
        elif block_id == "scenarios":
            item.setdefault("actors", [])
            item.setdefault("steps", ["执行场景"])
            item.setdefault("expected_outcomes", ["完成场景"])
            item.setdefault("requirement_ids", [])
        elif block_id == "architecture":
            if str(item.get("kind", "")).casefold() == "relation":
                item.setdefault("source_id", "")
                item.setdefault("predicate", "relatedTo")
                item.setdefault("target_id", "")
                item.pop("description", None)
                item.pop("requirement_ids", None)
            else:
                item.setdefault("description", str(item.get("name", item.get("id", ""))))
                item.setdefault("requirement_ids", [])
        normalized_items.append(item)
    normalized = {
        "items": normalized_items,
        "diagnostics": payload.get("diagnostics", []),
        "coverage_decisions": payload.get("coverage_decisions", []),
    }
    return replace(response, payload=normalized)


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
        self.dependencies = configured_dependencies(dependencies)
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

    def _save_state(
        self,
        state: dict[str, object],
        block_id: str,
        *,
        expected_content_revision: int | None = None,
    ) -> dict[str, object] | None:
        """Persist a block only if the human-editable source is unchanged.

        The revision check and write live in one SQLite ``BEGIN IMMEDIATE``
        transaction.  That closes the check-then-save race where a reviewer
        could edit the workbench between two separate connections and have a
        stale LLM response overwrite that edit.
        """
        repository = self.dependencies.repository_factory(self.workspace_path / ".rflp" / "model.db")
        try:
            with repository.transaction():
                if expected_content_revision is not None:
                    latest = repository.load_workbench()
                    latest_revision = int(
                        (latest or {}).get(
                            "content_revision",
                            (latest or {}).get("revision", 0),
                        )
                        or 0
                    )
                    if latest_revision != int(expected_content_revision):
                        return None
                repository.save_workbench(state, f"requirements.enrichment.{block_id}")
        finally:
            repository.close()
        return state

    @staticmethod
    def _snapshot_is_current(
        current: dict[str, object],
        snapshot_content_revision: int,
        snapshot_input_hash: str,
    ) -> bool:
        scope = current.get("project_scope")
        scope = scope if isinstance(scope, dict) else {}
        return (
            int(
                current.get(
                    "content_revision", current.get("revision", 0)
                )
                or 0
            )
            == int(snapshot_content_revision)
            and str(scope.get("input_hash", "")) == str(snapshot_input_hash)
        )

    def _commit_validated_block(
        self,
        validated: Any,
        *,
        snapshot_content_revision: int,
        snapshot_input_hash: str,
    ) -> dict[str, object] | None:
        """Validate, reconcile, and persist one block in one repository tx."""

        repository = self.dependencies.repository_factory(
            self.workspace_path / ".rflp" / "model.db"
        )
        try:
            with repository.transaction():
                current = repository.load_workbench()
                if not isinstance(current, dict):
                    raise ContractViolation("requirements workbench is empty")
                if not self._snapshot_is_current(
                    current, snapshot_content_revision, snapshot_input_hash
                ):
                    return None
                merged = merge_block_result(current, validated)
                # Reconciliation can remap model-provided entity IDs.  Check
                # cross-block references after that remap, before anything is
                # persisted, so a malformed scenario cannot poison the whole
                # workbench or make later page loads fail.
                validate_project_references(merged)
                repository.save_workbench(
                    merged,
                    f"requirements.enrichment.{validated.block_id}",
                )
                if hasattr(repository, "record_audit"):
                    repository.record_audit(
                        "requirements.analysis_block_merged",
                        {
                            "block_id": validated.block_id,
                            "input_hash": validated.input_hash,
                            "output_hash": validated.output_hash,
                            "content_revision": snapshot_content_revision,
                        },
                    )
            return merged
        finally:
            repository.close()

    def _heartbeat(self, job_id: str) -> bool:
        current = self.jobs.get(job_id) or {}
        lease_id = str(current.get("lease_id", ""))
        if not lease_id or not hasattr(self.jobs, "heartbeat"):
            return True
        return self.jobs.heartbeat(job_id, lease_id) is not None

    @staticmethod
    def _analysis_entity_ids(state: dict[str, object]) -> set[str]:
        return {
            str(item.get("id"))
            for group in (
                "claims",
                "structured_requirements",
                "stakeholders",
                "concerns",
                "needs",
                "scenarios",
            )
            for item in state.get(group, ())
            if isinstance(item, dict) and item.get("id")
        }

    def _execute_block_batch(
        self,
        job_id: str,
        model: GenerativeModel,
        state: dict[str, object],
        request_state: dict[str, object],
        block: Any,
        pack: dict[str, object],
        *,
        expected_content_revision: int,
        input_hash: str,
    ) -> tuple[dict[str, object] | None, list[str], dict[str, object] | None]:
        """Execute one model request and commit it through the existing CAS.

        Both the legacy aggregate runner and the parent/child coordinator use
        this seam.  Keeping request construction, source repair, validation,
        semantic checks and the CAS commit together prevents the two paths
        from drifting apart.
        """

        request_block = next(
            (
                candidate
                for candidate in build_analysis_blocks(request_state, pack)
                if str(candidate.id) == str(block.id)
            ),
            block,
        )
        request = build_block_request(request_state, request_block, pack)
        with _LeaseHeartbeat(self, job_id):
            response = model.complete_json(request)
        response = _legacy_fixture_response(
            response, str(block.id), request_state
        )
        repaired_payload, repair = repair_source_region_ids(
            response.payload,
            allowed_source_region_ids(request_state),
        )
        if repair is not None:
            response = replace(
                response,
                payload=repaired_payload,
                repaired=True,
            )
        validated = validate_and_build_result(
            response,
            state=request_state,
            block_id=str(block.id),
        )
        semantic_validator = AnalysisSemanticValidator()
        semantic_issues = semantic_validator.validate(validated, request_state)
        if semantic_issues:
            validated = semantic_validator.discard_unknown_relations(
                validated, semantic_issues
            )
        semantic_validator.assert_valid(validated, request_state)
        before = self._analysis_entity_ids(state)
        committed = self._commit_validated_block(
            validated,
            snapshot_content_revision=expected_content_revision,
            snapshot_input_hash=input_hash,
        )
        if committed is None:
            return None, [], repair
        after = self._analysis_entity_ids(committed)
        return committed, sorted(after - before), repair

    def _execute_block_job(
        self,
        job_id: str,
        model: GenerativeModel | None,
        block_id: str,
    ) -> dict[str, object]:
        """Run exactly one analysis block as a durable child Job."""

        started = time.monotonic()
        job = self.jobs.get(job_id) or {}
        payload = job.get("payload") if isinstance(job.get("payload"), dict) else {}
        state = self._load_state()
        expected_content_revision = int(
            payload.get(
                "content_revision",
                state.get("content_revision", state.get("revision", 0)),
            )
            or 0
        )
        expected_input_hash = str(payload.get("input_hash", ""))
        input_hash = self._input_hash(state)
        statuses: dict[str, str] = {block_id: "queued"}
        diagnostics: list[dict[str, object]] = []
        repairs: list[dict[str, object]] = []
        failure_stage = "snapshot"
        if expected_input_hash and expected_input_hash != input_hash:
            self.jobs.update(
                job_id,
                {
                    "status": "superseded",
                    "blocks": {block_id: "superseded"},
                    "failure_stage": "snapshot",
                    "diagnostics": [
                        {
                            "code": "analysis_superseded",
                            "message": "需求输入已变化，旧的分析子任务不能继续合并。",
                        }
                    ],
                },
            )
            return {
                "status": "superseded",
                "block_id": block_id,
                "blocks": {block_id: "superseded"},
                "diagnostics": [
                    {
                        "code": "analysis_superseded",
                        "message": "需求输入已变化，旧的分析子任务不能继续合并。",
                    }
                ],
            }

        pack = compose_pack_selection(state.get("analysis_config") or {})
        analysis_mode = str(payload.get("mode", payload.get("analysis_mode", "incremental")))
        if analysis_mode not in {"incremental", "coverage_audit", "full_reanalysis"}:
            analysis_mode = "incremental"
        delta_region_ids = tuple(
            str(value) for value in payload.get("delta_region_ids", ()) if str(value)
        )
        snapshot = build_project_snapshot(
            state,
            mode=analysis_mode,
            delta_region_ids=delta_region_ids,
        )
        batches = source_batches(snapshot, batch_size=20)
        blocks = build_analysis_blocks(state, pack)
        block = next(
            (candidate for candidate in blocks if str(candidate.id) == block_id),
            None,
        )
        if block is None:
            raise ContractViolation(f"未知分析块: {block_id}")
        self.jobs.update(
            job_id,
            {
                "status": "running",
                "input_hash": input_hash,
                "blocks": statuses,
                "block_states": statuses,
                "analysis_mode": analysis_mode,
                "model": getattr(model, "model_id", "") or "local-profile",
                "source_total": len(snapshot["input_regions"]),
                "batch_count": len(batches),
            },
        )
        if model is None:
            diagnostic = {
                "code": "generative_model_unavailable",
                "severity": "warning",
                "message": "当前未配置可用 LLM，已保留 accepted 基线。",
            }
            statuses[block_id] = "degraded"
            self.jobs.update(
                job_id,
                {
                    "blocks": statuses,
                    "block_states": statuses,
                    "failure_stage": "model_unavailable",
                    "diagnostics": [diagnostic],
                },
            )
            return {
                "status": "degraded",
                "block_id": block_id,
                "blocks": statuses,
                "diagnostics": [diagnostic],
            }

        working_state = state
        failed_statuses: list[str] = []
        for batch_index, batch in enumerate(batches, start=1):
            latest = self._load_state()
            latest_revision = int(
                latest.get("content_revision", latest.get("revision", 0)) or 0
            )
            if latest_revision != expected_content_revision:
                statuses[block_id] = "superseded"
                diagnostic = {
                    "code": "analysis_superseded",
                    "message": "提交分块结果时检测到人工内容版本变化。",
                }
                diagnostics.append(diagnostic)
                break
            if not self._heartbeat(job_id):
                statuses[block_id] = "interrupted"
                diagnostics.append(
                    {
                        "code": "job_lease_lost",
                        "message": "Job lease 已失效，当前 Block 已中断。",
                    }
                )
                break
            statuses[block_id] = "running"
            request_state = {
                **working_state,
                "analysis_input_regions": list(batch),
                "analysis_mode": analysis_mode,
                "delta_region_ids": list(delta_region_ids),
                "analysis_batch_index": batch_index,
                "analysis_batch_count": len(batches),
            }
            batch_started = time.monotonic()
            try:
                failure_stage = "llm_request"
                committed, merged_ids, repair = self._execute_block_batch(
                    job_id,
                    model,
                    working_state,
                    request_state,
                    block,
                    pack,
                    expected_content_revision=expected_content_revision,
                    input_hash=input_hash,
                )
                if repair is not None:
                    repairs.append(repair)
                    diagnostics.append(
                        {
                            "code": str(repair.get("code", "source_region_repair")),
                            "severity": "warning",
                            "message": "已记录来源区域引用修复诊断。",
                            "details": repair,
                        }
                    )
                if committed is None:
                    statuses[block_id] = "superseded"
                    diagnostics.append(
                        {
                            "code": "analysis_superseded",
                            "message": "提交分块结果时检测到人工内容版本变化。",
                        }
                    )
                    break
                working_state = committed
                statuses[block_id] = "succeeded"
                del merged_ids
            except AdapterFailure as exc:
                statuses[block_id] = "failed"
                failed_statuses.append("failed")
                diagnostics.append(
                    {
                        "code": "llm_block_failed",
                        "message": str(exc),
                        "batch_index": batch_index,
                    }
                )
            except (ContractViolation, ValueError, TypeError) as exc:
                statuses[block_id] = "degraded"
                failed_statuses.append("degraded")
                diagnostics.append(
                    {
                        "code": "llm_block_degraded",
                        "message": str(exc),
                        "batch_index": batch_index,
                    }
                )
            except Exception as exc:
                statuses[block_id] = "failed"
                failed_statuses.append("failed")
                diagnostics.append(
                    {
                        "code": "llm_block_failed",
                        "exception_type": type(exc).__name__,
                        "message": str(exc),
                        "batch_index": batch_index,
                    }
                )
            finally:
                self.jobs.update(
                    job_id,
                    {
                        "blocks": statuses,
                        "block_states": statuses,
                        "block_durations_ms": {
                            **dict(
                                (self.jobs.get(job_id) or {}).get(
                                    "block_durations_ms", {}
                                )
                            ),
                            str(batch_index): max(
                                0, int((time.monotonic() - batch_started) * 1000)
                            ),
                        },
                    },
                )
            if statuses[block_id] in {"superseded", "interrupted"}:
                break
            if not self._heartbeat(job_id):
                statuses[block_id] = "interrupted"
                diagnostics.append(
                    {
                        "code": "job_lease_lost",
                        "message": "Job lease 已失效，当前 Block 已中断。",
                    }
                )
                break

        status = statuses[block_id]
        if status == "succeeded" and failed_statuses:
            status = "degraded"
            statuses[block_id] = status
        metadata: dict[str, object] = {
            "parent_job_id": payload.get("parent_job_id", ""),
            "block_id": block_id,
            "duration_ms": max(0, int((time.monotonic() - started) * 1000)),
            "failure_stage": "" if status == "succeeded" else failure_stage,
            "repair": repairs,
        }
        self.jobs.update(
            job_id,
            {
                "status": status,
                "blocks": statuses,
                "block_states": statuses,
                "diagnostics": diagnostics,
                "metadata": metadata,
            },
        )
        return {
            "status": status,
            "block_id": block_id,
            "blocks": statuses,
            "diagnostics": diagnostics,
            "repair": repairs,
        }

    def _finalize_coordinated_run(
        self,
        job_id: str,
        *,
        status: str,
        statuses: dict[str, str],
        diagnostics: list[dict[str, object]],
        expected_content_revision: int,
    ) -> str:
        """Merge the final summary into the newest workbench atomically.

        A derived-model action can commit a new workbench revision without
        changing ``content_revision``.  Loading outside the write transaction
        therefore allowed a finishing background Job to overwrite a freshly
        generated MBSE model.  Read, merge and save under one SQLite
        transaction so the latest derived state is always the base.
        """

        repository = self.dependencies.repository_factory(
            self.workspace_path / ".rflp" / "model.db"
        )
        try:
            with repository.transaction():
                state = repository.load_workbench()
                if not isinstance(state, dict):
                    return "superseded"
                current_content_revision = int(
                    state.get("content_revision", state.get("revision", 0)) or 0
                )
                if current_content_revision != int(expected_content_revision):
                    return "superseded"

                analysis = dict(state.get("auto_analysis") or {})
                analysis.update(
                    {
                        "status": status,
                        "job_id": job_id,
                        "mode": "llm-project-analysis",
                        "input_hash": self._input_hash(state),
                        "blocks": statuses,
                        "block_states": statuses,
                        "diagnostics": diagnostics[-12:],
                    }
                )
                state["auto_analysis"] = analysis
                state["analysis_coverage"] = evaluate_project_coverage(
                    state, compose_pack_selection(state.get("analysis_config") or {})
                )
                if status == "completed":
                    try:
                        from rflp_lite.application.requirements_workbench import generate_model
                        from rflp_lite.application.mbse_modeling import generate_mbse_revision

                        if not state.get("rflp"):
                            state = generate_model(state)
                        if not state.get("mbse"):
                            state = generate_mbse_revision(state)
                    except (
                        ContractViolation,
                        InvariantViolation,
                        ValueError,
                        TypeError,
                        KeyError,
                    ):
                        diagnostics.append(
                            {
                                "code": "derived_model_deferred",
                                "severity": "warning",
                                "message": "分块结果已保存，正式 RFLP 仍需在需求检查页生成。",
                            }
                        )
                        state["auto_analysis"]["diagnostics"] = diagnostics[-12:]
                repository.save_workbench(state, "requirements.analysis.final")
        finally:
            repository.close()
        return status

    def _execute(
        self,
        job_id: str,
        model: GenerativeModel | None,
        expected_input_hash: str | None,
        previous_blocks: dict[str, object] | None = None,
        retry_blocks: frozenset[str] | None = None,
    ) -> dict[str, object]:
        state = self._load_state()
        expected_content_revision = int(
            (self.jobs.get(job_id) or {}).get("payload", {}).get(
                "content_revision",
                state.get("content_revision", state.get("revision", 0)),
            )
            or 0
        )
        input_hash = self._input_hash(state)
        if expected_input_hash and expected_input_hash != input_hash:
            raise ContractViolation("需求输入已变化，旧的增量任务不能继续合并")
        pack = compose_pack_selection(state.get("analysis_config") or {})
        analysis_mode = str(
            (self.jobs.get(job_id) or {}).get("payload", {}).get(
                "analysis_mode", "incremental"
            )
        )
        if analysis_mode not in {"incremental", "coverage_audit", "full_reanalysis"}:
            analysis_mode = "incremental"
        delta_region_ids = tuple(
            str(value)
            for value in (self.jobs.get(job_id) or {}).get("payload", {}).get(
                "delta_region_ids", ()
            )
            if str(value)
        )
        snapshot = build_project_snapshot(
            state, mode=analysis_mode, delta_region_ids=delta_region_ids
        )
        batches = source_batches(snapshot, batch_size=20)
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
                "block_states": statuses,
                "model": getattr(model, "model_id", "") or "local-profile",
                "retryable": True,
                "analysis_mode": analysis_mode,
                "source_total": len(snapshot["input_regions"]),
                "batch_count": len(batches),
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
            # A model-unavailable run still obeys the same optimistic lock as
            # normal enrichment, so it cannot clobber a simultaneous edit.
            if self._save_state(
                state,
                "baseline",
                expected_content_revision=expected_content_revision,
            ) is None:
                self.jobs.update(
                    job_id,
                    {
                        "retryable": False,
                        "superseded_by_content_revision": int(
                            self._load_state().get("content_revision", 0) or 0
                        ),
                    },
                )
                return {"status": "superseded", "blocks": statuses, "merged_item_ids": []}
            self.jobs.update(job_id, {"blocks": statuses})
            return {"status": "degraded", "merged_item_ids": [], "blocks": statuses}

        merged_ids: list[str] = []
        diagnostics: list[dict[str, object]] = []
        run_interrupted = False
        attempted_source_ids: set[str] = set()
        block_batch_failures: set[str] = set()
        source_block_states: dict[str, dict[str, str]] = {
            str(item.get("id")): {} for item in snapshot["input_regions"]
        }
        for batch_index, batch in enumerate(batches, start=1):
            request_state = {
                **state,
                "analysis_input_regions": list(batch),
                "analysis_mode": analysis_mode,
                "delta_region_ids": list(delta_region_ids),
                "analysis_batch_index": batch_index,
                "analysis_batch_count": len(batches),
            }
            for block_id, block in block_map.items():
                if (batch_index == 1 and statuses[block_id] == "succeeded") or (
                    retry_blocks is not None and block_id not in retry_blocks
                ):
                    continue
                latest_before = self._load_state()
                latest_content_revision = int(
                    latest_before.get(
                        "content_revision", latest_before.get("revision", 0)
                    )
                    or 0
                )
                if latest_content_revision != expected_content_revision:
                    statuses[block_id] = "superseded"
                    self.jobs.update(
                        job_id,
                        {
                            "blocks": statuses,
                            "superseded_by_content_revision": latest_content_revision,
                            "retryable": False,
                        },
                    )
                    return {
                        "status": "superseded",
                        "blocks": statuses,
                        "merged_item_ids": sorted(set(merged_ids)),
                        "diagnostics": [
                            {
                                "code": "analysis_superseded",
                                "message": "需求或人工编辑已产生新内容版本，旧分析结果未继续写入。",
                            }
                        ],
                    }
                if not self._heartbeat(job_id):
                    statuses[block_id] = "interrupted"
                    run_interrupted = True
                    diagnostics.append(
                        {
                            "code": "job_lease_lost",
                            "block_id": block_id,
                            "message": "Job lease 已失效，当前 Block 已中断。",
                        }
                    )
                    break
                started = time.monotonic()
                statuses[block_id] = "running"
                self.jobs.update(
                    job_id,
                    {"status": "running", "blocks": statuses, "block_states": statuses, "active_block": block_id, "batch_index": batch_index},
                )
                block_status = "succeeded"
                try:
                    committed, batch_merged_ids, repair = self._execute_block_batch(
                        job_id,
                        model,
                        state,
                        request_state,
                        block,
                        pack,
                        expected_content_revision=expected_content_revision,
                        input_hash=input_hash,
                    )
                    if committed is None:
                        statuses[block_id] = "superseded"
                        self.jobs.update(
                            job_id,
                            {
                                "blocks": statuses,
                                "retryable": False,
                                "superseded_by_content_revision": int(
                                    self._load_state().get("content_revision", 0) or 0
                                ),
                            },
                        )
                        return {
                            "status": "superseded",
                            "blocks": statuses,
                            "merged_item_ids": sorted(set(merged_ids)),
                            "diagnostics": [
                                {
                                    "code": "analysis_superseded",
                                    "message": "提交分块结果时检测到人工内容版本变化。",
                                }
                            ],
                        }
                    state = committed
                    request_state = {
                        **state,
                        "analysis_input_regions": list(batch),
                        "analysis_mode": analysis_mode,
                        "delta_region_ids": list(delta_region_ids),
                        "analysis_batch_index": batch_index,
                        "analysis_batch_count": len(batches),
                    }
                    merged_ids.extend(batch_merged_ids)
                    if repair is not None:
                        diagnostics.append(
                            {
                                "code": str(repair.get("code", "source_region_repair")),
                                "severity": "warning",
                                "message": "已记录来源区域引用修复诊断。",
                                "details": repair,
                            }
                        )
                    statuses[block_id] = "succeeded"
                except AdapterFailure as exc:
                    block_status = "failed"
                    block_batch_failures.add(block_id)
                    statuses[block_id] = "failed"
                    diagnostics.append({"code": "llm_block_failed", "block_id": block_id, "batch_index": batch_index, "message": str(exc)})
                except (ContractViolation, ValueError, TypeError) as exc:
                    block_status = "degraded"
                    block_batch_failures.add(block_id)
                    statuses[block_id] = "degraded"
                    diagnostics.append({"code": "llm_block_degraded", "block_id": block_id, "batch_index": batch_index, "message": str(exc)})
                except Exception as exc:
                    # Provider SDKs and local model adapters are allowed to
                    # raise implementation-specific exceptions.  A single
                    # block must not escape the orchestration loop and leave
                    # the durable Job and Workbench disagreeing about the
                    # outcome.
                    block_status = "failed"
                    block_batch_failures.add(block_id)
                    statuses[block_id] = "failed"
                    diagnostics.append(
                        {
                            "code": "llm_block_failed",
                            "block_id": block_id,
                            "batch_index": batch_index,
                            "exception_type": type(exc).__name__,
                            "message": str(exc),
                        }
                    )
                finally:
                    self.jobs.update(
                        job_id,
                        {
                            "blocks": statuses,
                            "block_states": statuses,
                            "block_durations_ms": {
                                **(
                                    self.jobs.get(job_id) or {}
                                ).get("block_durations_ms", {}),
                                f"{block_id}:{batch_index}": max(0, int((time.monotonic() - started) * 1000)),
                            },
                        },
                    )
                if block_status == "succeeded":
                    for item in batch:
                        source_id = str(item.get("id", ""))
                        if source_id:
                            source_block_states[source_id][block_id] = "succeeded"
                else:
                    for item in batch:
                        source_id = str(item.get("id", ""))
                        if source_id:
                            source_block_states[source_id][block_id] = block_status
                if not self._heartbeat(job_id):
                    statuses[block_id] = "interrupted"
                    run_interrupted = True
                    diagnostics.append(
                        {
                            "code": "job_lease_lost",
                            "block_id": block_id,
                            "message": "Job lease 已失效，后续 Block 不再继续。",
                        }
                    )
                    break
            attempted_source_ids.update(str(item.get("id", "")) for item in batch if str(item.get("id", "")))
            completed_sources = {
                source_id
                for source_id, block_states in source_block_states.items()
                if set(block_states) == set(block_map)
                and set(block_states.values()) == {"succeeded"}
            }
            self.jobs.update(
                job_id,
                {
                    "source_total": len(snapshot["input_regions"]),
                    "source_attempted": len(attempted_source_ids),
                    "source_analyzed": len(completed_sources),
                    "batch_count": len(batches),
                    "batch_index": batch_index,
                },
            )
            if run_interrupted:
                break

        for failed_block in block_batch_failures:
            if statuses.get(failed_block) == "succeeded":
                statuses[failed_block] = "degraded"

        terminal = set(statuses.values())
        status = (
            "interrupted"
            if run_interrupted
            else "completed"
            if terminal == {"succeeded"}
            else "degraded"
        )
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
                "block_states": statuses,
                "diagnostics": diagnostics[-12:],
            }
        )
        state["auto_analysis"] = analysis
        state["analysis_progress"] = {
            "attempted_source_ids": sorted(attempted_source_ids),
            "analyzed_source_ids": sorted(completed_sources),
            "source_block_states": source_block_states,
            "source_total": len(snapshot["input_regions"]),
        }
        state["analysis_source_registry"] = sorted(
            set(str(value) for value in state.get("analysis_source_registry", ()))
            | set(completed_sources)
        )
        state["analysis_coverage"] = evaluate_project_coverage(state, pack)
        if self._save_state(
            state,
            "final",
            expected_content_revision=expected_content_revision,
        ) is None:
            latest = self._load_state()
            statuses = {
                **statuses,
                "final": "superseded",
            }
            self.jobs.update(
                job_id,
                {
                    "blocks": statuses,
                    "retryable": False,
                    "superseded_by_content_revision": int(
                        latest.get("content_revision", latest.get("revision", 0)) or 0
                    ),
                },
            )
            return {
                "status": "superseded",
                "blocks": statuses,
                "merged_item_ids": sorted(set(merged_ids)),
                "diagnostics": [
                    {
                        "code": "analysis_superseded",
                        "message": "提交分析汇总时检测到人工内容版本变化。",
                    }
                ],
            }
        self.jobs.update(
            job_id,
            {
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
        retry_blocks: frozenset[str] | None = None,
        analysis_mode: str = "incremental",
        delta_region_ids: tuple[str, ...] = (),
        content_revision: int | None = None,
        mode: str | None = None,
        snapshot_revision: int | None = None,
        snapshot_content_revision: int | None = None,
        analysis_config_hash: str | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, object]:
        from rflp_lite.application.intelligence.analysis_coordinator import AnalysisCoordinator

        state = self._load_state()
        expected = input_hash or self._input_hash(state)
        effective_mode = mode or analysis_mode
        effective_content_revision = int(
            snapshot_content_revision
            if snapshot_content_revision is not None
            else content_revision
            if content_revision is not None
            else state.get("content_revision", state.get("revision", 0))
            or 0
        )
        return AnalysisCoordinator(
            self.workspace_path,
            dependencies=self.dependencies,
            job_service=self.jobs,
            runner=self,
        ).submit(
            model,
            input_hash=expected,
            mode=effective_mode,
            delta_region_ids=delta_region_ids,
            snapshot_revision=int(
                snapshot_revision if snapshot_revision is not None else state.get("revision", 0) or 0
            ),
            snapshot_content_revision=effective_content_revision,
            analysis_config_hash=str(analysis_config_hash or ""),
            idempotency_key=idempotency_key,
        )

    def run(
        self, model: GenerativeModel | None, *, input_hash: str | None = None
    ) -> dict[str, object]:
        """Submit and wait; useful for deterministic application-level tests."""

        # ``run`` is the explicit synchronous/test helper.  Give it a fresh
        # key so it cannot accidentally attach to an already queued automatic
        # analysis for the same snapshot (the production async path still
        # uses deterministic idempotency keys).
        record = self.submit(
            model,
            input_hash=input_hash,
            idempotency_key=f"manual-run:{uuid.uuid4().hex}",
        )
        job_id = str(record["id"])
        for _ in range(600):
            current = self.jobs.get(job_id)
            if current and current.get("status") in {"succeeded", "completed", "failed", "degraded", "interrupted", "superseded"}:
                if current.get("status") == "succeeded" and isinstance(current.get("result"), dict) and current["result"].get("status") == "completed":
                    # Keep the synchronous helper's historical return alias;
                    # the durable JobStatus remains ``succeeded``.
                    return {**current, "status": "completed"}
                return current
            time.sleep(0.05)
        raise TimeoutError("enrichment job did not finish")

    def retry(self, job_id: str, model: GenerativeModel | None) -> dict[str, object]:
        previous = self.jobs.get(job_id)
        if previous is None:
            raise ContractViolation("enrichment job not found")
        if str(previous.get("kind")) == "requirements.analysis":
            from rflp_lite.application.intelligence.analysis_coordinator import AnalysisCoordinator

            return AnalysisCoordinator(
                self.workspace_path,
                dependencies=self.dependencies,
                job_service=self.jobs,
                runner=self,
            ).retry_failed(job_id, model)
        self._assert_retryable_job(previous)
        latest = self._load_state()
        latest_hash = self._input_hash(latest)
        latest_content_revision = int(
            latest.get("content_revision", latest.get("revision", 0)) or 0
        )
        previous_payload = previous.get("payload") if isinstance(previous.get("payload"), dict) else {}
        previous_content_revision = int(
            previous_payload.get("content_revision", 0) or 0
        )
        if (
            str(previous.get("input_hash", "")) != latest_hash
            or previous_content_revision != latest_content_revision
        ):
            self.jobs.update(
                job_id,
                {
                    "status": "superseded",
                    "retryable": False,
                    "superseded_by_content_revision": latest_content_revision,
                },
            )
        blocks = previous.get("blocks") if isinstance(previous.get("blocks"), dict) else {}
        return self.submit(
            model,
            input_hash=latest_hash,
            previous_blocks={key: value for key, value in blocks.items() if value == "succeeded"},
            analysis_mode=str(previous_payload.get("analysis_mode", "incremental")),
            delta_region_ids=tuple(
                str(value)
                for value in previous_payload.get("delta_region_ids", ())
                if str(value)
            ),
            snapshot_revision=int(latest.get("revision", 0) or 0),
            content_revision=latest_content_revision,
            analysis_config_hash=str(previous_payload.get("analysis_config_hash", "")),
        )

    def retry_block(
        self, job_id: str, block_id: str, model: GenerativeModel | None
    ) -> dict[str, object]:
        previous = self.jobs.get(job_id)
        if previous is None:
            raise ContractViolation("enrichment job not found")
        if str(previous.get("kind")) == "requirements.analysis":
            from rflp_lite.application.intelligence.analysis_coordinator import AnalysisCoordinator

            return AnalysisCoordinator(
                self.workspace_path,
                dependencies=self.dependencies,
                job_service=self.jobs,
                runner=self,
            ).retry_block(job_id, block_id, model)
        self._assert_retryable_job(previous)
        latest = self._load_state()
        latest_hash = self._input_hash(latest)
        latest_content_revision = int(
            latest.get("content_revision", latest.get("revision", 0)) or 0
        )
        previous_payload = previous.get("payload") if isinstance(previous.get("payload"), dict) else {}
        previous_content_revision = int(
            previous_payload.get("content_revision", 0) or 0
        )
        if (
            str(previous.get("input_hash", "")) != latest_hash
            or previous_content_revision != latest_content_revision
        ):
            self.jobs.update(
                job_id,
                {
                    "status": "superseded",
                    "retryable": False,
                    "superseded_by_content_revision": latest_content_revision,
                },
            )
        blocks = previous.get("blocks") if isinstance(previous.get("blocks"), dict) else {}
        if block_id not in blocks:
            raise ContractViolation(f"未知分析块: {block_id}")
        if blocks.get(block_id) == "succeeded":
            raise ContractViolation("成功分析块不需要重试")
        return self.submit(
            model,
            input_hash=latest_hash,
            previous_blocks=dict(blocks),
            retry_blocks=frozenset({block_id}),
            analysis_mode=str(previous_payload.get("analysis_mode", "incremental")),
            delta_region_ids=tuple(
                str(value)
                for value in previous_payload.get("delta_region_ids", ())
                if str(value)
            ),
            snapshot_revision=int(latest.get("revision", 0) or 0),
            content_revision=latest_content_revision,
            analysis_config_hash=str(previous_payload.get("analysis_config_hash", "")),
        )

    @staticmethod
    def _assert_retryable_job(previous: dict[str, object]) -> None:
        kind = str(previous.get("kind", "requirements.enrichment"))
        status = str(previous.get("status", "failed"))
        if kind not in _ENRICHMENT_JOB_KINDS | {"requirements.analysis"}:
            raise ContractViolation("只能重试需求 enrichment Job")
        if status not in _RETRYABLE_JOB_STATUSES:
            raise ContractViolation("只有 failed、degraded 或 interrupted enrichment Job 可以重试")


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
