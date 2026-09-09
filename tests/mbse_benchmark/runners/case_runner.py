"""Run one benchmark case against the real application services."""

from __future__ import annotations

import json
import multiprocessing
from pathlib import Path
import tempfile
import time
from typing import Any, Mapping

from rflp_lite.adapters.openai_compatible_model import OpenAICompatibleModel
from rflp_lite.bootstrap.v2 import build_v2_services
from rflp_lite.domain.canonical import canonical_json, to_primitive
from rflp_lite.domain.entities import EntityKind, EntityStatus, Producer, make_entity
from rflp_lite.domain.model import AddEntity, Patch, Relate, UpdateEntity
from rflp_lite.domain.relations import RelationPredicate
from rflp_lite.runtime.structured_model import StructuredModelRuntime
from rflp_lite.methodology.coverage_matrix import build_requirement_coverage



def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(canonical_json(value) + "\n", encoding="utf-8")


def _graph_payload(graph) -> dict[str, object]:
    return {
        "project_id": graph.project_id,
        "revision": graph.revision,
        "snapshot_hash": graph.snapshot_hash,
        "entities": [item.as_dict() for item in graph.entities],
        "relations": [
            {
                "id": item.id,
                "source_id": item.source_id,
                "predicate": item.predicate.value,
                "target_id": item.target_id,
                "evidence_ids": list(item.evidence_ids),
            }
            for item in graph.relations
        ],
    }


def _apply_fault_injection(services, project_id: str, case: Mapping[str, object]) -> dict[str, object]:
    """Add the explicit CASE-05 physical design through the normal Patch path."""

    repository = services.repository(project_id)
    graph = repository.load_graph(project_id)
    requirements = {
        str(entity.payload.get("fixture_id")): entity
        for entity in graph.entities
        if entity.kind is EntityKind.REQUIREMENT
        and isinstance(entity.payload, Mapping)
        and str(entity.payload.get("fixture_id", ""))
    }
    operations: list[object] = []
    for raw_requirement in case.get("requirements", ()):
        if not isinstance(raw_requirement, Mapping):
            continue
        fixture_id = str(raw_requirement.get("id", ""))
        entity = requirements.get(fixture_id)
        if entity is None:
            continue
        operations.append(
            UpdateEntity(
                entity.id,
                {
                    "payload": {
                        "metric": dict(raw_requirement.get("metric", {})),
                        "statement": str(raw_requirement.get("statement", "")),
                        "fault_injection_id": fixture_id,
                    }
                },
            )
        )

    function = make_entity(
        EntityKind.FUNCTION,
        "配送车物理可行性控制",
        {"purpose": "验证重量与续航约束", "fault_injection": True},
        status=EntityStatus.ACCEPTED,
        producer=Producer.IMPORT,
        confidence=1.0,
        revision=graph.revision,
    )
    logical = make_entity(
        EntityKind.LOGICAL_COMPONENT,
        "物理可行性评估组件",
        {"responsibility": "汇总质量、能量和功耗", "fault_injection": True},
        status=EntityStatus.ACCEPTED,
        producer=Producer.IMPORT,
        confidence=1.0,
        revision=graph.revision,
    )
    operations.extend((AddEntity(function), AddEntity(logical)))
    physical_ids: list[str] = []
    for raw_component in case.get("physical_design", ()):
        if not isinstance(raw_component, Mapping):
            continue
        component = make_entity(
            EntityKind.PHYSICAL_BLOCK,
            str(raw_component.get("name", "physical component")),
            {
                "fault_injection_id": str(raw_component.get("id", "")),
                "mass": raw_component.get("mass"),
                "mass_unit": raw_component.get("mass_unit", "kg"),
                "energy": raw_component.get("energy"),
                "energy_unit": raw_component.get("energy_unit", "Wh"),
                "average_power": case.get("power_budget", {}).get("average_power")
                if isinstance(case.get("power_budget"), Mapping)
                else None,
                "candidate": False,
            },
            status=EntityStatus.ACCEPTED,
            producer=Producer.IMPORT,
            confidence=1.0,
            revision=graph.revision,
        )
        physical_ids.append(component.id)
        operations.append(AddEntity(component))

    operations.append(Relate(function.id, RelationPredicate.ALLOCATED_TO, logical.id))
    for entity in requirements.values():
        if isinstance(entity.payload, Mapping) and entity.payload.get("fixture_id") in {"REQ-WEIGHT", "REQ-RUNTIME"}:
            operations.append(Relate(entity.id, RelationPredicate.SATISFIED_BY, function.id))
    for physical_id in physical_ids:
        operations.append(Relate(logical.id, RelationPredicate.ALLOCATED_TO, physical_id))
    if not operations:
        return {"status": "skipped", "reason": "no fault-injection operations"}
    patch = Patch.create(
        project_id,
        "benchmark.case-05.fault-injection",
        tuple(operations),
        "注入 CASE-05 明确给出的物理设计和约束",
        graph.revision,
    )
    revision = repository.append_patch(project_id, patch, graph.revision)
    return {"status": "applied", "patch_id": patch.id, "revision": revision.sequence}


def _run_case_inner(
    case: Mapping[str, object],
    output_dir: Path,
    runtime_config: Mapping[str, object] | None = None,
) -> None:
    started = time.time()
    case_id = str(case["case_id"])
    project_id = case_id.lower()
    workspace = Path(tempfile.mkdtemp(prefix=f"ai4mbse-{project_id}-"))
    execution: dict[str, object] = {
        "status": "running",
        "case_id": case_id,
        "project_id": project_id,
        "workspace": str(workspace),
        "runtime": "configured-llm" if runtime_config else "offline-rule",
        "entrypoint": "build_v2_services -> AnalysisService.run -> WorkflowRunner",
        "started_at": started,
    }
    services = None
    try:
        runtime = (
            StructuredModelRuntime(OpenAICompatibleModel(dict(runtime_config)))
            if runtime_config
            else None
        )
        services = build_v2_services(
            workspace,
            runtime=runtime,
            runtime_config=dict(runtime_config) if runtime_config else None,
            config_dir=workspace / ".rflp-config",
        )
        services.projects.create(project_id, str(case.get("system", project_id)))
        input_path = output_dir / "input.json"
        _write_json(input_path, case)
        services.projects.ingest(project_id, input_path)
        injection = None
        if case_id == "CASE-05":
            injection = _apply_fault_injection(services, project_id, case)
            _write_json(output_dir / "fault_injection.json", injection)
        summary = services.analysis(project_id).run(project_id, force_new=True)
        repository = services.repository(project_id)
        graph = services.model(project_id).graph(project_id)
        run = repository.load_run(project_id, summary.run_id)
        issues = repository.list_issues(project_id)
        audit = repository.audit_summary(project_id, summary.run_id)
        _write_json(output_dir / "run_summary.json", to_primitive(summary))
        _write_json(output_dir / "run_ledger.json", to_primitive(run) if run else {})
        _write_json(output_dir / "model.json", _graph_payload(graph))
        _write_json(output_dir / "coverage_matrix.json", build_requirement_coverage(graph).as_dict())
        _write_json(output_dir / "issues.json", issues)
        _write_json(output_dir / "audit.json", audit)
        execution.update(
            {
                "status": "completed",
                "run_status": str(getattr(summary.status, "value", summary.status)),
                "run_id": summary.run_id,
                "revision": graph.revision,
                "entity_count": len(graph.entities),
                "relation_count": len(graph.relations),
                "injection": injection,
            }
        )
    except BaseException as exc:  # Persist the failure before the child exits.
        execution.update(
            {
                "status": "failed",
                "exception_type": type(exc).__name__,
                "exception": str(exc),
            }
        )
    finally:
        execution["completed_at"] = time.time()
        execution["elapsed_seconds"] = round(float(execution["completed_at"]) - started, 6)
        _write_json(output_dir / "execution.json", execution)
        if services is not None:
            for repository in getattr(services, "_repositories", {}).values():
                repository.close()


def _child_entry(
    case: Mapping[str, object],
    output_dir: str,
    runtime_config: Mapping[str, object] | None = None,
) -> None:
    _run_case_inner(case, Path(output_dir), runtime_config)


def run_case(
    case: Mapping[str, object],
    output_dir: Path,
    *,
    repeat_index: int = 1,
    timeout_seconds: int = 60,
    runtime_config: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Run one isolated real-system case and always return a result record."""

    output_dir = output_dir / f"repeat_{repeat_index:02d}"
    output_dir.mkdir(parents=True, exist_ok=True)
    context = multiprocessing.get_context("spawn")
    process = context.Process(
        target=_child_entry,
        args=(dict(case), str(output_dir), dict(runtime_config) if runtime_config else None),
    )
    started = time.time()
    process.start()
    process.join(max(1, int(timeout_seconds)))
    if process.is_alive():
        process.terminate()
        process.join(5)
        execution = {
            "status": "blocked",
            "case_id": case.get("case_id", ""),
            "repeat_index": repeat_index,
            "timeout_seconds": timeout_seconds,
            "elapsed_seconds": round(time.time() - started, 6),
            "exception_type": "TimeoutError",
            "exception": f"case exceeded {timeout_seconds}s",
        }
        _write_json(output_dir / "execution.json", execution)
    elif not (output_dir / "execution.json").exists():
        execution = {
            "status": "failed",
            "case_id": case.get("case_id", ""),
            "repeat_index": repeat_index,
            "exit_code": process.exitcode,
            "elapsed_seconds": round(time.time() - started, 6),
            "exception_type": "WorkerExitError",
            "exception": "worker exited before writing execution.json",
        }
        _write_json(output_dir / "execution.json", execution)
    execution = json.loads((output_dir / "execution.json").read_text(encoding="utf-8"))
    execution["repeat_index"] = repeat_index
    _write_json(output_dir / "execution.json", execution)
    return {
        "case_id": str(case.get("case_id", "")),
        "repeat_index": repeat_index,
        "output_dir": str(output_dir),
        "execution": execution,
        "graph": json.loads((output_dir / "model.json").read_text(encoding="utf-8"))
        if (output_dir / "model.json").exists()
        else {},
        "coverage_matrix": json.loads((output_dir / "coverage_matrix.json").read_text(encoding="utf-8"))
        if (output_dir / "coverage_matrix.json").exists()
        else {},
        "run_summary": json.loads((output_dir / "run_summary.json").read_text(encoding="utf-8"))
        if (output_dir / "run_summary.json").exists()
        else {},
        "run_ledger": json.loads((output_dir / "run_ledger.json").read_text(encoding="utf-8"))
        if (output_dir / "run_ledger.json").exists()
        else {},
        "issues": json.loads((output_dir / "issues.json").read_text(encoding="utf-8"))
        if (output_dir / "issues.json").exists()
        else [],
        "audit": json.loads((output_dir / "audit.json").read_text(encoding="utf-8"))
        if (output_dir / "audit.json").exists()
        else {},
    }
