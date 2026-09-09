"""HTML pages and read-only workflow view models for the Harness UI."""

from __future__ import annotations

from collections import deque
from dataclasses import asdict, is_dataclass
from enum import Enum
from pathlib import Path
from typing import Mapping

from fastapi import APIRouter, Request
from fastapi.templating import Jinja2Templates

from rflp_lite.domain.canonical import canonical_hash
from rflp_lite.domain.entities import EntityKind
from rflp_lite.domain.model import ModelGraph
from rflp_lite.methodology.contracts import Phase
from rflp_lite.methodology.gates import gate_for_phase, global_gate
from rflp_lite.methodology.tasks import task_catalog, tasks_for_phase


resource_pages = APIRouter()
templates = Jinja2Templates(directory=Path(__file__).resolve().parent / "templates")


_PHASES: tuple[tuple[Phase, str], ...] = (
    (Phase.OPERATIONAL, "Operational"),
    (Phase.FUNCTIONAL, "Functional"),
    (Phase.LOGICAL_PHYSICAL, "Logical/Physical"),
    (Phase.ASSURANCE, "Assurance"),
    (Phase.CLOSURE, "Closure"),
)
_TRACE_STAGES: tuple[tuple[EntityKind, str], ...] = (
    (EntityKind.REQUIREMENT, "Requirement"),
    (EntityKind.FUNCTION, "Function"),
    (EntityKind.LOGICAL_COMPONENT, "Logical"),
    (EntityKind.PHYSICAL_BLOCK, "Physical"),
    (EntityKind.VERIFICATION_CASE, "Verification"),
)
_ROOT_CAUSES = {
    "missing_stakeholder": "stakeholder",
    "missing_lifecycle": "lifecycle",
    "missing_scenario": "scenario",
    "missing_use_case": "scenario",
    "missing_requirement": "requirement",
    "missing_function": "function",
    "broken_requirement_function_trace": "function",
    "incomplete_rflp_chain": "architecture",
    "broken_requirement_rflp_trace": "architecture",
    "missing_verification": "verification",
    "broken_requirement_verification_trace": "verification",
}
_SUGGESTED_TASKS = {
    "stakeholder": "stakeholder_analysis",
    "lifecycle": "lifecycle_analysis",
    "scenario": "scenario_exploration",
    "requirement": "system_requirement_derivation",
    "function": "function_identification",
    "architecture": "logical_analysis",
    "verification": "verification_validation",
}


def _plain(value: object) -> object:
    """Convert mixed legacy/new service objects to JSON/Jinja values."""

    if is_dataclass(value):
        return _plain(asdict(value))
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (tuple, list, set, frozenset)):
        return [_plain(item) for item in value]
    return value


def _mapping(value: object) -> dict[str, object]:
    clean = _plain(value)
    return dict(clean) if isinstance(clean, Mapping) else {}


def _state(request: Request, name: str, factory):
    value = getattr(request.app.state, name, None)
    if value is None:
        value = factory()
        setattr(request.app.state, name, value)
    return value


def remember_run(request: Request, project_id: str, run: Mapping[str, object]) -> None:
    """Remember a Web-triggered result until a repository list API is available."""

    records = _state(request, "web_analysis_runs", dict)
    records.setdefault(project_id, []).append(dict(_plain(run)))
    records[project_id] = records[project_id][-20:]


def remember_repair(request: Request, project_id: str, repair: Mapping[str, object]) -> None:
    repairs = _state(request, "web_repairs", dict)
    repairs.setdefault(project_id, []).append(dict(_plain(repair)))
    repairs[project_id] = repairs[project_id][-20:]


def _services(request: Request):
    return request.app.state.container.v2


def _phase_value(value: object) -> str:
    return str(getattr(value, "value", value or ""))


def _status_value(value: object, default: str = "") -> str:
    return _phase_value(value) or default


def _runtime_metadata(services, run: Mapping[str, object] | None = None) -> dict[str, object]:
    run_data = run or {}
    recorded = _mapping(run_data.get("runtime"))
    try:
        active = _mapping(services.settings.active_config())
    except Exception:
        active = {}
    profile_id = str(
        run_data.get("model_profile")
        or run_data.get("profile_id")
        or recorded.get("profile_id")
        or active.get("id")
        or "offline-rule"
    )
    provider_id = str(
        run_data.get("provider_id")
        or run_data.get("provider")
        or recorded.get("provider_id")
        or active.get("provider_id")
        or ("openai-compatible" if active else "offline")
    )
    model_id = str(
        run_data.get("model_id")
        or recorded.get("model_id")
        or active.get("model")
        or ("rule-runtime" if not active else "")
    )
    raw_mode = str(
        run_data.get("runtime_mode")
        or recorded.get("mode")
        or active.get("mode")
        or ("configured" if active else "offline")
    ).casefold()
    if raw_mode in {"injected", "injected runtime"}:
        mode = "Injected Runtime"
    elif raw_mode in {"configured", "configured model", "active"} or active:
        mode = "Configured Model"
    else:
        mode = "Offline Rule Mode"
    return {
        "profile_id": profile_id,
        "provider_id": provider_id,
        "model_id": model_id,
        "mode": mode,
        "configured": mode == "Configured Model",
        "source": "run" if run_data and (run_data.get("provider_id") or run_data.get("model_id") or run_data.get("model_profile")) else "active" if active else "fallback",
    }


def _normalize_run(raw: object) -> dict[str, object] | None:
    value = _mapping(raw)
    if not value:
        return None
    run_id = str(value.get("run_id") or value.get("id") or "")
    if not run_id:
        return None
    normalized = dict(value)
    normalized["run_id"] = run_id
    normalized["phase"] = _status_value(value.get("phase"), "operational")
    normalized["status"] = _status_value(value.get("status"), "queued")
    normalized["completed_tasks"] = list(value.get("completed_tasks", ()))
    normalized["diagnostics"] = list(value.get("diagnostics", ()))
    normalized["steps"] = [_mapping(item) for item in value.get("steps", ()) if _mapping(item)]
    return normalized


def _repository_latest_run(services, project_id: str) -> dict[str, object] | None:
    repository = services.repository(project_id)
    list_runs = getattr(repository, "list_runs", None)
    if callable(list_runs):
        try:
            runs = list_runs(project_id)
            candidates = [_normalize_run(item) for item in runs]
            candidates = [item for item in candidates if item]
            if candidates:
                return candidates[-1]
        except Exception:
            pass
    # The current legacy repository has no list_runs port. This read-only
    # fallback is isolated to the Web presentation adapter.
    connection = getattr(repository, "_connection", None)
    if connection is not None:
        try:
            row = connection.execute(
                "SELECT id FROM runs WHERE project_id = ? ORDER BY rowid DESC LIMIT 1",
                (project_id,),
            ).fetchone()
            if row is not None:
                return _normalize_run(repository.load_run(project_id, str(row[0])))
        except Exception:
            pass
    return None


def _latest_run(request: Request, services, project_id: str) -> dict[str, object] | None:
    records = _state(request, "web_analysis_runs", dict).get(project_id, ())
    if records:
        remembered = _normalize_run(records[-1])
        if remembered:
            repository = services.repository(project_id)
            try:
                stored = _normalize_run(repository.load_run(project_id, remembered["run_id"]))
            except Exception:
                stored = None
            if stored:
                stored_steps = stored.get("steps", ())
                merged = {**stored, **remembered}
                if not remembered.get("steps"):
                    merged["steps"] = stored_steps
                return merged
            return remembered
        return _repository_latest_run(services, project_id)
    return _repository_latest_run(services, project_id)


def _aggregate_pipeline_steps(services, project_id: str, run: dict[str, object] | None) -> dict[str, object] | None:
    if not run or run.get("steps"):
        return run
    phase_results = run.get("phase_results", ())
    values = phase_results.values() if isinstance(phase_results, Mapping) else phase_results
    repository = services.repository(project_id)
    steps: list[dict[str, object]] = []
    for item in values or ():
        phase_run_id = _mapping(item).get("run_id")
        if not phase_run_id:
            continue
        try:
            stored = _normalize_run(repository.load_run(project_id, str(phase_run_id)))
        except Exception:
            stored = None
        if stored:
            steps.extend(stored.get("steps", ()))
    if not steps:
        return run
    return {**run, "steps": steps}


def _issue_payload(raw: object, *, fallback_phase: Phase | None = None) -> dict[str, object]:
    value = _mapping(raw)
    code = str(value.get("code") or "issue")
    root_cause = str(value.get("root_cause") or _ROOT_CAUSES.get(code, "evidence"))
    rollback = value.get("rollback_phase") or value.get("suggested_rollback")
    rollback_value = _status_value(rollback) if rollback else _status_value(fallback_phase)
    entity_ids = [str(item) for item in value.get("entity_ids", ())]
    return {
        "id": str(value.get("id") or f"issue-{canonical_hash((code, tuple(entity_ids), rollback_value))[:12]}"),
        "code": code,
        "severity": str(value.get("severity") or "error"),
        "root_cause": root_cause,
        "entity_ids": entity_ids,
        "suggested_task": str(value.get("suggested_task") or _SUGGESTED_TASKS.get(root_cause, "manual_review")),
        "rollback_phase": rollback_value,
        "evidence_gap": bool(value.get("evidence_gap", code.startswith("missing_"))),
        "status": str(value.get("status") or "open"),
        "message": str(value.get("message") or f"{code} requires review"),
    }


def _gate_payload(raw: object, *, fallback_phase: Phase | None = None) -> dict[str, object]:
    value = _mapping(raw)
    gate_id = str(value.get("gate_id") or "Global-Gate")
    raw_issues = value.get("issues", ())
    issues = [_issue_payload(item, fallback_phase=fallback_phase) for item in raw_issues]
    passed = bool(value.get("passed", not issues))
    return {
        "gate_id": gate_id,
        "passed": passed,
        "status": "passed" if passed else "failed",
        "issues": issues,
        "rollback_phase": _status_value(value.get("rollback_phase"), "") or None,
    }


def _record_gate_results(run: Mapping[str, object] | None) -> dict[str, dict[str, object]]:
    if not run:
        return {}
    raw = run.get("gate_results", ())
    values = raw.values() if isinstance(raw, Mapping) else raw
    result: dict[str, dict[str, object]] = {}
    for item in values or ():
        payload = _mapping(item)
        phase = str(payload.get("phase") or payload.get("phase_id") or "")
        gate = _gate_payload(payload)
        if not phase:
            phase = gate["gate_id"]
        result[phase] = gate
    return result


def _current_task(services, project_id: str, graph: ModelGraph, run: Mapping[str, object] | None, runtime: Mapping[str, object]) -> dict[str, object]:
    steps = list(run.get("steps", ())) if run else []
    step = next((item for item in steps if item.get("status") == "running"), None)
    if step is None and steps:
        step = max(steps, key=lambda item: (int(item.get("attempt", 0) or 0), str(item.get("task_id", ""))))
    task_id = str(step.get("task_id", "")) if step else ""
    phase_values = {item.value for item, _label in _PHASES}
    phase = Phase(str(run.get("phase", Phase.OPERATIONAL.value))) if run and str(run.get("phase", "")) in phase_values else Phase.OPERATIONAL
    task = next((item for item in task_catalog() if item.id == task_id), None)
    if task is None:
        phase_tasks = tasks_for_phase(phase)
        task = phase_tasks[0] if phase_tasks else None
        task_id = task.id if task else "awaiting_task"
    context: dict[str, object] = {
        "revision": graph.revision,
        "entity_count": len(graph.entities),
        "relation_count": len(graph.relations),
        "evidence_count": 0,
        "token_estimate": 0,
    }
    try:
        if task is not None:
            from rflp_lite.methodology.context import ContextBuilder

            bundle = ContextBuilder().build(graph, task)
            context.update(
                evidence_count=len(bundle.evidence),
                token_estimate=bundle.token_estimate,
            )
    except Exception:
        pass
    step_status = str(step.get("status", "queued")) if step else "queued"
    diagnostics = [str(item) for item in (step.get("diagnostics", ()) if step else ())]
    if step_status == "completed":
        validation = "Passed"
    elif diagnostics:
        validation = "; ".join(diagnostics)
    else:
        validation = "Not run"
    patch_id = "—"
    if step:
        patch_id = str(step.get("output_patch_id") or step.get("patch_id") or "—")
    return {
        "task_id": task_id,
        "phase": phase.value,
        "status": step_status,
        "input_context": context,
        "evidence_count": context["evidence_count"],
        "provider_id": str(step.get("provider_id") or runtime.get("provider_id", "")) if step else runtime.get("provider_id", ""),
        "model_id": str(step.get("model_id") or runtime.get("model_id", "")) if step else runtime.get("model_id", ""),
        "attempt": int(step.get("attempt", 0) or 0) if step else 0,
        "patch_id": patch_id,
        "validation": validation,
        "diagnostics": diagnostics,
    }


def _phase_status(run: Mapping[str, object] | None, phase: Phase) -> str:
    if not run:
        return "ready" if phase is Phase.OPERATIONAL else "pending"
    results = run.get("phase_results", ())
    values = results.values() if isinstance(results, Mapping) else results
    for item in values or ():
        value = _mapping(item)
        if _status_value(value.get("phase")) == phase.value:
            return _status_value(value.get("status"), "queued")
    if _status_value(run.get("phase")) == phase.value:
        return _status_value(run.get("status"), "queued")
    closure = _mapping(run.get("closure"))
    if phase is Phase.CLOSURE and closure.get("status"):
        return str(closure["status"])
    return "pending"


def build_analysis_view(request: Request, project_id: str) -> dict[str, object]:
    services = _services(request)
    project = _mapping(services.projects.summary(project_id))
    graph = services.model(project_id).graph(project_id)
    run = _aggregate_pipeline_steps(services, project_id, _latest_run(request, services, project_id))
    runtime = _runtime_metadata(services, run)
    record_gates = _record_gate_results(run)
    gate_results: list[dict[str, object]] = []
    for phase, _label in _PHASES:
        if phase is Phase.CLOSURE:
            result = record_gates.get(phase.value) or record_gates.get("Global-Gate")
            if result is None:
                result = _gate_payload(global_gate(graph), fallback_phase=Phase.ASSURANCE)
        else:
            result = record_gates.get(phase.value)
            if result is None:
                result = _gate_payload(gate_for_phase(phase, graph), fallback_phase=phase)
        result = dict(result)
        result["phase"] = phase.value
        gate_results.append(result)
    global_result = next((item for item in gate_results if item["gate_id"] == "Global-Gate"), None)
    if global_result is None:
        global_result = _gate_payload(global_gate(graph), fallback_phase=Phase.ASSURANCE)
        global_result["phase"] = Phase.CLOSURE.value
    stored_issues = []
    try:
        stored_issues = [_issue_payload(item) for item in services.model(project_id).issues(project_id)]
    except Exception:
        pass
    all_issues = list(stored_issues)
    for gate in gate_results:
        all_issues.extend(gate["issues"])
    unique: dict[str, dict[str, object]] = {}
    for issue in all_issues:
        unique[str(issue["id"])] = issue
    all_issues = list(unique.values())
    repair_records = _state(request, "web_repairs", dict).get(project_id, ())
    repair = dict(repair_records[-1]) if repair_records else _mapping(run.get("repair")) if run else {}
    if not repair:
        repair = {
            "status": "idle",
            "root_cause": "—",
            "rollback_phase": "—",
            "rollback_task": "—",
            "automatic_round": 0,
            "manual_action": "Select a Gate issue to start a targeted repair.",
        }
    closure = _mapping(run.get("closure")) if run else {}
    if not closure:
        closure = {"status": "pending", "accepted_revision": None, "manifest": None}
    latest_run = dict(run) if run else None
    if latest_run is not None:
        latest_run["runtime"] = runtime
    gate_by_phase = {item["phase"]: item for item in gate_results}
    phase_states = [
        {
            "phase": phase.value,
            "name": label,
            "status": _phase_status(run, phase),
            "gate": gate_by_phase[phase.value],
        }
        for phase, label in _PHASES
    ]
    view = {
        "project": {**project, "revision": graph.revision},
        "project_id": project_id,
        "current_revision": graph.revision,
        "graph_hash": graph.snapshot_hash,
        "runtime": runtime,
        "active_runtime": runtime,
        "active_model": runtime,
        "run_status": latest_run.get("status", "ready") if latest_run else "ready",
        "latest_run": latest_run,
        "current_run": latest_run,
        "phases": phase_states,
        "phase_states": phase_states,
        "current_task": _current_task(services, project_id, graph, run, runtime),
        "task_ledger": list(latest_run.get("steps", ())) if latest_run else [],
        "gate_results": gate_results,
        "gate_result": global_result,
        "global_gate": global_result,
        "gate_issues": all_issues,
        "issues": all_issues,
        "repair": repair,
        "repair_results": list(repair_records),
        "closure": closure,
        "closure_state": closure,
    }
    return view


def _trace_node(project_id: str, entity, stage: str) -> dict[str, object]:
    return {
        "stage": stage,
        "kind": entity.kind.value,
        "id": entity.id,
        "name": entity.meta.name,
        "status": entity.meta.status.value,
        "href": f"/projects/{project_id}/entities?kind={entity.kind.value}#entity-{entity.id}",
    }


def _kind_path(graph: ModelGraph, adjacency: Mapping[str, tuple[str, ...]], start_id: str, target_kind: EntityKind) -> tuple[str, ...] | None:
    index = graph.entity_index
    queue: deque[tuple[str, tuple[str, ...]]] = deque([(start_id, (start_id,))])
    visited = {start_id}
    while queue:
        current, path = queue.popleft()
        if current != start_id and index.get(current) and index[current].kind is target_kind:
            return path
        for target in adjacency.get(current, ()):
            if target not in visited and target in index:
                visited.add(target)
                queue.append((target, path + (target,)))
    return None


def build_trace_view(request: Request, project_id: str) -> dict[str, object]:
    services = _services(request)
    graph = services.model(project_id).graph(project_id)
    index = graph.entity_index
    adjacency: dict[str, list[str]] = {}
    for relation in graph.relations:
        adjacency.setdefault(relation.source_id, []).append(relation.target_id)
    adjacency_tuple = {key: tuple(value) for key, value in adjacency.items()}
    paths: list[dict[str, object]] = []
    issues: list[dict[str, object]] = []
    for requirement in sorted((item for item in graph.entities if item.kind is EntityKind.REQUIREMENT), key=lambda item: item.id):
        ids: list[str | None] = [requirement.id]
        function_path = _kind_path(graph, adjacency_tuple, requirement.id, EntityKind.FUNCTION)
        ids.append(function_path[-1] if function_path else None)
        logical_path = _kind_path(graph, adjacency_tuple, ids[-1], EntityKind.LOGICAL_COMPONENT) if ids[-1] else None
        ids.append(logical_path[-1] if logical_path else None)
        physical_path = _kind_path(graph, adjacency_tuple, ids[-1], EntityKind.PHYSICAL_BLOCK) if ids[-1] else None
        ids.append(physical_path[-1] if physical_path else None)
        verification_path = _kind_path(graph, adjacency_tuple, requirement.id, EntityKind.VERIFICATION_CASE)
        ids.append(verification_path[-1] if verification_path else None)
        nodes: list[dict[str, object] | None] = []
        missing: list[str] = []
        for entity_id, (_kind, stage) in zip(ids, _TRACE_STAGES):
            entity = index.get(entity_id) if entity_id else None
            nodes.append(_trace_node(project_id, entity, stage) if entity else None)
            if entity is None:
                missing.append(stage)
                issues.append({
                    "code": f"missing_trace_{stage.casefold()}",
                    "message": f"{requirement.meta.name} has no {stage} link",
                    "entity_ids": [requirement.id],
                    "severity": "warning",
                })
        path: dict[str, object] = {
            "path_id": f"trace-{canonical_hash((project_id, requirement.id))[:12]}",
            "complete": not missing,
            "missing": missing,
            "nodes": nodes,
        }
        for node, (_kind, stage) in zip(nodes, _TRACE_STAGES):
            path[stage.casefold()] = node
        paths.append(path)
    return {
        "project_id": project_id,
        "revision": graph.revision,
        "graph_hash": graph.snapshot_hash,
        "stages": [stage for _kind, stage in _TRACE_STAGES],
        "paths": paths,
        "issues": issues,
    }


def build_settings_view(request: Request) -> dict[str, object]:
    services = _services(request)
    settings = _mapping(services.settings.list_profiles())
    return {"settings": settings, "runtime": _runtime_metadata(services)}


def _v2(request: Request):
    return request.app.state.container.v2


@resource_pages.get("/ui/projects", name="projects_page")
def projects_page(request: Request):
    return templates.TemplateResponse(request=request, name="projects.html", context={"projects": _v2(request).projects.list(), "active": "projects"})


@resource_pages.get("/ui/projects/{project_id}/analysis", name="analysis_page")
def analysis_page(request: Request, project_id: str):
    view = build_analysis_view(request, project_id)
    return templates.TemplateResponse(request=request, name="analysis.html", context={**view, "analysis": view, "active": "analysis"})


@resource_pages.get("/ui/projects/{project_id}/model", name="model_page")
def model_page(request: Request, project_id: str):
    services = _v2(request)
    trace = build_trace_view(request, project_id)
    return templates.TemplateResponse(request=request, name="model.html", context={"project": services.projects.summary(project_id), "project_id": project_id, "trace": trace, "active": "model"})


@resource_pages.get("/ui/projects/{project_id}/evidence", name="evidence_page")
def evidence_page(request: Request, project_id: str):
    services = _v2(request)
    return templates.TemplateResponse(request=request, name="evidence-issues.html", context={"project": services.projects.summary(project_id), "evidence": services.evidence(project_id).list(project_id), "issues": services.model(project_id).issues(project_id), "project_id": project_id, "active": "evidence"})


@resource_pages.get("/ui/settings", name="settings_page")
def settings_page(request: Request):
    view = build_settings_view(request)
    return templates.TemplateResponse(request=request, name="settings.html", context={**view, "active": "settings"})
