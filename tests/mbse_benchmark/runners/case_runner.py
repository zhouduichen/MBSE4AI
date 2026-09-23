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
from rflp_lite.domain.canonical import canonical_hash, canonical_json, to_primitive
from rflp_lite.domain.entities import EntityKind, EntityStatus, Producer, make_entity
from rflp_lite.domain.errors import ConcurrentModificationError
from rflp_lite.domain.model import AddEntity, Patch, Relate, UpdateEntity
from rflp_lite.domain.relations import RelationPredicate
from rflp_lite.runtime.structured_model import StructuredModelRuntime
from rflp_lite.methodology.coverage_matrix import build_requirement_coverage
from rflp_lite.methodology.closure import evaluate_strict_closure
from rflp_lite.repository.sqlite import SQLiteModelRepository
from tests.mbse_benchmark.scenarios import (
    BenchmarkScenario,
    scenario_contract,
)
from tests.mbse_benchmark.runners.experiment_contract import (
    BenchmarkInputEnvelope,
    ExperimentTelemetry,
    assert_model_visible_payload_tokens,
    input_sha256,
    runtime_provider_id,
)
from tests.mbse_benchmark.runners.scenario_pipeline import (
    ModelGraphNormalizer,
    ScenarioRunner,
    TASK_SPEC,
)


class _EvaluatorBoundaryModel:
    """Enforce the evaluator-only boundary for real Harness calls.

    A/B already validate their request payload in ``ScenarioRunner``.  The
    Harness path enters through ``StructuredModelRuntime`` instead, so it
    needs the same guard at the last benchmark-owned boundary before the
    provider adapter is reached.
    """

    def __init__(self, model, evaluator_key_tokens: frozenset[str]):
        self._model = model
        self._evaluator_key_tokens = evaluator_key_tokens

    def complete_json(self, request):
        assert_model_visible_payload_tokens(
            request.user_payload,
            self._evaluator_key_tokens,
        )
        return self._model.complete_json(request)

    def __getattr__(self, name: str):
        return getattr(self._model, name)



def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(canonical_json(value) + "\n", encoding="utf-8")


def _write_canonical_input(path: Path, envelope: BenchmarkInputEnvelope) -> None:
    """Persist the exact bytes shared by every A–E scenario."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(envelope.canonical_bytes + b"\n")


def _apply_scenario_runtime_controls(
    runtime_config: Mapping[str, object],
    contract,
) -> dict[str, object]:
    """Bind Harness repair behavior to the declared A–E control.

    The product runtime exposes bounded feedback and the deterministic
    completion bridge as profile options.  A comparison must not silently
    inherit a profile's latency-oriented defaults, otherwise D would claim
    ``repair_enabled=false`` while still issuing repair/completion passes or E
    would claim the full path while those passes were disabled.
    """

    config = dict(runtime_config)
    repair_enabled = bool(contract.repair_enabled)
    config.update({
        "vertical_feedback": repair_enabled,
        "automatic_operational_completion": repair_enabled,
        "vertical_completion_bridge": repair_enabled,
    })
    return config


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


def _run_analysis(
    services,
    project_id: str,
    ingest_result: Mapping[str, object],
    runtime_config: Mapping[str, object] | None,
    analysis_path: str,
    scenario: str = BenchmarkScenario.E_FULL_HARNESS.value,
):
    contract = scenario_contract(scenario)
    if analysis_path == "vertical":
        if not runtime_config:
            raise ValueError("vertical benchmark path requires an explicit LLM runtime config")
        document_id = str(ingest_result.get("document_id", ""))
        try:
            region_count = int(ingest_result.get("region_count", 0) or 0)
        except (TypeError, ValueError):
            region_count = 0
        return services.generation(project_id).generate(
            project_id,
            document_ids=(document_id,) if document_id and region_count > 0 else (),
            force_new=True,
        )
    if contract.has_repair:
        return services.analysis(project_id).run(project_id, force_new=True)
    return services.analysis(project_id).run(
        project_id,
        force_new=True,
        max_repair_rounds=0,
    )


def _run_cas_probe(repository, project_id: str) -> dict[str, object]:
    """Exercise the real repository CAS boundary in an isolated probe project."""

    # SQLite revision ids are database-global. Use a fresh repository so the
    # probe cannot collide with the case's legitimate revision history or
    # mutate the observed engineering model.
    del repository, project_id
    with tempfile.TemporaryDirectory(prefix="ai4mbse-cas-") as root:
        probe_repository = SQLiteModelRepository(Path(root) / "cas.db")
        probe_project = "cas-probe"
        probe_repository.ensure_project(probe_project)
        graph = probe_repository.load_graph(probe_project)
        entity = make_entity(
            EntityKind.SYSTEM,
            "CAS probe",
            status=EntityStatus.CANDIDATE,
            producer=Producer.RULE,
            revision=graph.revision,
        )
        patch = Patch.create(
            probe_project,
            "benchmark.cas_probe",
            (AddEntity(entity),),
            "benchmark CAS probe",
            graph.revision,
        )
        probe_repository.append_patch(probe_project, patch, graph.revision)
        try:
            probe_repository.append_patch(probe_project, patch, graph.revision)
        except ConcurrentModificationError:
            probe_repository.close()
            return {"stale_write_rejected": True, "first_revision": 1}
        probe_repository.close()
        return {"stale_write_rejected": False, "first_revision": 1}


def _run_case_inner(
    case: Mapping[str, object],
    output_dir: Path,
    runtime_config: Mapping[str, object] | None = None,
    model_visible_key_tokens: frozenset[str] | None = None,
    analysis_path: str = "lifecycle",
    scenario: str = BenchmarkScenario.E_FULL_HARNESS.value,
    comparison_mode: str = "natural",
    total_output_token_budget: int | None = None,
) -> None:
    started = time.time()
    case_id = str(case["case_id"])
    project_id = case_id.lower()
    input_envelope = BenchmarkInputEnvelope.from_case(case)
    scenario_contract(scenario)
    workspace = Path(tempfile.mkdtemp(prefix=f"ai4mbse-{project_id}-"))
    execution: dict[str, object] = {
        "status": "running",
        "case_id": case_id,
        "project_id": project_id,
        "workspace": str(workspace),
        "runtime": "configured-llm" if runtime_config else "offline-rule",
        "entrypoint": (
            "build_v2_services -> ModelGenerationService.generate -> five-stage vertical path"
            if analysis_path == "vertical"
            else "build_v2_services -> AnalysisService.run -> WorkflowRunner"
        ),
        "analysis_path": analysis_path,
        "scenario": scenario,
        "started_at": started,
    }
    services = None
    telemetry_events: list[object] = []
    try:
        contract = scenario_contract(scenario)
        effective_runtime_config = dict(runtime_config) if runtime_config else None
        if effective_runtime_config is not None and contract.generation_shape == "harness":
            effective_runtime_config = _apply_scenario_runtime_controls(
                effective_runtime_config,
                contract,
            )
        if comparison_mode == "budget_matched" and total_output_token_budget is not None:
            if effective_runtime_config is None:
                raise ValueError("budget-matched comparison requires a configured model")
            effective_runtime_config["benchmark_total_output_token_budget"] = int(total_output_token_budget)
        if contract.scenario in {
            BenchmarkScenario.A_BARE_ONE_SHOT,
            BenchmarkScenario.B_BARE_STAGED,
        }:
            if not effective_runtime_config:
                raise ValueError(
                    "A/B benchmark scenarios require the explicit configured model used by E"
                )
            model = OpenAICompatibleModel(
                dict(effective_runtime_config),
                telemetry_sink=telemetry_events.append,
            )
            scenario_output = ScenarioRunner(ModelGraphNormalizer()).run(
                input_envelope,
                contract,
                model,
                project_id=project_id,
                token_budget=int(effective_runtime_config.get("benchmark_token_budget", 3000) or 3000),
                model_visible_key_tokens=model_visible_key_tokens,
            )
            graph = scenario_output.graph
            closure = evaluate_strict_closure(graph)
            summary = {
                "run_id": f"{project_id}-{contract.scenario.value}",
                "project_id": project_id,
                "status": "completed",
                "phase": "bare_model",
                "completed_tasks": [],
                "diagnostics": ["bare scenario: configured model call; repository, verifier, repair and CAS bypassed"],
                "closure": {
                    "status": "completed" if closure.passed else "blocked",
                    "issues": [item.as_dict() for item in closure.issues],
                    "manifest": None,
                },
                "scenario_controls": {
                    "verifier": contract.has_verifier,
                    "gate": contract.gate_enabled,
                    "repair": contract.has_repair,
                    "cas": contract.has_cas,
                },
            }
            _write_canonical_input(output_dir / "input.json", input_envelope)
            _write_json(output_dir / "run_summary.json", summary)
            _write_json(output_dir / "run_ledger.json", {})
            _write_json(output_dir / "model.json", _graph_payload(graph))
            _write_json(output_dir / "coverage_matrix.json", build_requirement_coverage(graph).as_dict())
            _write_json(output_dir / "issues.json", [])
            _write_json(output_dir / "audit.json", {"events": []})
            metadata = scenario_output.metadata.as_dict()
            metadata["normalization_audit"] = scenario_output.normalization_audit.as_dict()
            metadata["input_byte_length"] = len(input_envelope.canonical_bytes)
            metadata["input_sha256"] = input_sha256(input_envelope)
            metadata["benchmark_token_budget"] = int(
                effective_runtime_config.get("benchmark_token_budget", 3000)
                or 3000
            )
            metadata["telemetry"] = ExperimentTelemetry.from_events(
                telemetry_events,
                wall_latency_ms=int((time.time() - started) * 1000),
                comparison_mode=comparison_mode,
                total_output_token_budget=total_output_token_budget,
                input_cost_per_1m_tokens=_as_float(effective_runtime_config.get("input_cost_per_1m_tokens")),
                output_cost_per_1m_tokens=_as_float(effective_runtime_config.get("output_cost_per_1m_tokens")),
            ).as_dict()
            _write_json(output_dir / "metadata.json", metadata)
            execution.update(
                {
                    "status": "completed",
                    "run_status": "completed",
                    "run_id": summary["run_id"],
                    "revision": graph.revision,
                    "entity_count": len(graph.entities),
                    "relation_count": len(graph.relations),
                    "input_hash": input_envelope.input_hash,
                    "input_byte_length": len(input_envelope.canonical_bytes),
                    "input_sha256": input_sha256(input_envelope),
                    "cas_probe": {},
                    "scenario_controls": summary["scenario_controls"],
                    "metadata": metadata,
                }
            )
            return
        if effective_runtime_config:
            model = OpenAICompatibleModel(
                dict(effective_runtime_config),
                telemetry_sink=telemetry_events.append,
            )
            if model_visible_key_tokens is not None:
                model = _EvaluatorBoundaryModel(model, model_visible_key_tokens)
            runtime = StructuredModelRuntime(model)
        else:
            runtime = None
        services = build_v2_services(
            workspace,
            runtime=runtime,
            runtime_config=effective_runtime_config,
            config_dir=workspace / ".rflp-config",
            verifier_enabled=contract.has_verifier,
        )
        services.projects.create(project_id, str(case.get("system", project_id)))
        input_path = output_dir / "input.json"
        _write_canonical_input(input_path, input_envelope)
        ingest_result = services.projects.ingest(project_id, input_path)
        injection = None
        if case_id == "CASE-05":
            injection = _apply_fault_injection(services, project_id, case)
            _write_json(output_dir / "fault_injection.json", injection)
        summary = _run_analysis(
            services,
            project_id,
            ingest_result if isinstance(ingest_result, Mapping) else {},
            effective_runtime_config,
            analysis_path,
            scenario,
        )
        repository = services.repository(project_id)
        graph = services.model(project_id).graph(project_id)
        run = repository.load_run(project_id, summary.run_id)
        issues = repository.list_issues(project_id)
        audit = repository.audit_summary(project_id, summary.run_id)
        cas_probe = _run_cas_probe(repository, project_id) if contract.has_cas else {}
        _write_json(output_dir / "run_summary.json", to_primitive(summary))
        _write_json(output_dir / "run_ledger.json", to_primitive(run) if run else {})
        _write_json(output_dir / "model.json", _graph_payload(graph))
        _write_json(output_dir / "coverage_matrix.json", build_requirement_coverage(graph).as_dict())
        _write_json(output_dir / "issues.json", issues)
        _write_json(output_dir / "audit.json", audit)
        ledger_payload = to_primitive(run) if run else {}
        ledger_metadata = ledger_payload.get("metadata", ledger_payload) if isinstance(ledger_payload, Mapping) else {}
        _write_json(output_dir / "metadata.json", _harness_metadata(
            input_envelope,
            contract,
            graph,
            runtime_config,
            ledger_metadata,
            telemetry_events=telemetry_events,
            comparison_mode=comparison_mode,
            total_output_token_budget=total_output_token_budget,
            execution_elapsed=time.time() - started,
        ))
        execution.update(
            {
                "status": "completed",
                "run_status": str(getattr(summary.status, "value", summary.status)),
                "run_id": summary.run_id,
                "revision": graph.revision,
                "entity_count": len(graph.entities),
                "relation_count": len(graph.relations),
                "input_hash": input_envelope.input_hash,
                "input_byte_length": len(input_envelope.canonical_bytes),
                "input_sha256": input_sha256(input_envelope),
                "injection": injection,
                "cas_probe": cas_probe,
                "scenario_controls": {
                    "verifier": contract.has_verifier,
                    "gate": contract.gate_enabled,
                    "repair": contract.has_repair,
                    "cas": contract.has_cas,
                },
            "metadata": json.loads((output_dir / "metadata.json").read_text(encoding="utf-8")),
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
    model_visible_key_tokens: frozenset[str] | None = None,
    analysis_path: str = "lifecycle",
    scenario: str = BenchmarkScenario.E_FULL_HARNESS.value,
    comparison_mode: str = "natural",
    total_output_token_budget: int | None = None,
) -> None:
    _run_case_inner(
        case,
        Path(output_dir),
        runtime_config,
        model_visible_key_tokens,
        analysis_path,
        scenario,
        comparison_mode,
        total_output_token_budget,
    )


def run_case(
    case: Mapping[str, object],
    output_dir: Path,
    *,
    repeat_index: int = 1,
    timeout_seconds: int = 60,
    runtime_config: Mapping[str, object] | None = None,
    model_visible_key_tokens: frozenset[str] | None = None,
    analysis_path: str = "lifecycle",
    scenario: str = BenchmarkScenario.E_FULL_HARNESS.value,
    comparison_mode: str = "natural",
    total_output_token_budget: int | None = None,
) -> dict[str, object]:
    """Run one isolated real-system case and always return a result record."""

    output_dir = output_dir / f"repeat_{repeat_index:02d}"
    output_dir.mkdir(parents=True, exist_ok=True)
    context = multiprocessing.get_context("spawn")
    process = context.Process(
        target=_child_entry,
        args=(
            dict(case),
            str(output_dir),
            dict(runtime_config) if runtime_config else None,
            model_visible_key_tokens,
            analysis_path,
            scenario,
            comparison_mode,
            total_output_token_budget,
        ),
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
        "cas_probe": execution.get("cas_probe", {}),
        "metadata": json.loads((output_dir / "metadata.json").read_text(encoding="utf-8"))
        if (output_dir / "metadata.json").exists()
        else {},
    }


def _harness_metadata(
    input_envelope: BenchmarkInputEnvelope,
    contract,
    graph,
    runtime_config: Mapping[str, object] | None,
    ledger_metadata: Mapping[str, object],
    *,
    telemetry_events: list[object],
    comparison_mode: str,
    total_output_token_budget: int | None,
    execution_elapsed: float,
) -> dict[str, object]:
    config = runtime_config or {}
    fallback_context = {
        "scenario": contract.scenario.value,
        "model": config.get("model", "rule-runtime"),
        "provider": runtime_provider_id(config),
        "input_hash": input_envelope.input_hash,
        "controls": {
            "verifier": contract.has_verifier,
            "gate": contract.gate_enabled,
            "repair": contract.has_repair,
            "cas": contract.has_cas,
        },
    }
    prompt_hash = ledger_metadata.get("prompt_hash") or canonical_hash(fallback_context)
    # ``task_spec_hash`` is the shared benchmark contract.  Harness runs also
    # have an implementation-specific lifecycle task hash; preserve it as a
    # separate field instead of making a fair A–E comparison fail merely
    # because Bare and Harness use different internal task decompositions.
    task_spec_hash = canonical_hash(TASK_SPEC)
    runtime_task_spec_hash = str(ledger_metadata.get("task_spec_hash", ""))
    telemetry = ExperimentTelemetry.from_events(
        telemetry_events,
        wall_latency_ms=int(execution_elapsed * 1000),
        comparison_mode=comparison_mode,
        total_output_token_budget=total_output_token_budget,
        input_cost_per_1m_tokens=_as_float(config.get("input_cost_per_1m_tokens")),
        output_cost_per_1m_tokens=_as_float(config.get("output_cost_per_1m_tokens")),
    )
    return {
        "scenario": contract.scenario.value,
        "model": str(config.get("model", "rule-runtime")),
        "provider": runtime_provider_id(config),
        "prompt_hash": str(prompt_hash),
        "task_spec_hash": str(task_spec_hash),
        "runtime_task_spec_hash": runtime_task_spec_hash,
        "temperature": _as_float(config.get("temperature")),
        "input_hash": input_envelope.input_hash,
        "input_byte_length": len(input_envelope.canonical_bytes),
        "input_sha256": input_sha256(input_envelope),
        "benchmark_token_budget": int(config.get("benchmark_token_budget", 3000) or 3000),
        "token_usage": ledger_metadata.get("token_usage") if isinstance(ledger_metadata.get("token_usage"), Mapping) else None,
        "latency_ms": max(0, int(execution_elapsed * 1000)),
        "graph_hash": graph.snapshot_hash,
        "verifier_enabled": contract.has_verifier,
        "gate_enabled": contract.gate_enabled,
        "repair_enabled": contract.has_repair,
        "cas_enabled": contract.has_cas,
        "telemetry": telemetry.as_dict(),
    }


def _as_float(value: object) -> float | None:
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None
