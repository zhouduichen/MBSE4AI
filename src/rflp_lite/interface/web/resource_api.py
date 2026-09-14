"""Resource-oriented API for the AI4MBSE Harness."""

from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path
from typing import Mapping
from uuid import uuid4

from fastapi import APIRouter, Request, UploadFile
from fastapi.responses import JSONResponse, Response

from rflp_lite.domain.entities import EntityKind
from rflp_lite.domain.errors import AdapterFailure, ConcurrentModificationError, ContractViolation, InputRequired, NotFoundError, RflpError
from rflp_lite.domain.model import AddEntity, Patch, Relate, UpdateEntity
from rflp_lite.application.model_export import graph_sysml
from rflp_lite.application.sysml_v2 import sysml_to_graph
from rflp_lite.application.projections.assurance import build_assurance_view
from rflp_lite.application.projections.behavior import build_behavior_view
from rflp_lite.application.projections.history import build_history_view, build_revision_diff
from rflp_lite.application.projections.operational import build_operational_view
from rflp_lite.application.projections.requirements import build_requirement_detail, build_requirements_view
from rflp_lite.application.projections.rflp import build_rflp_view
from rflp_lite.application.projections.traceability import build_traceability_view
from rflp_lite.diagrams.engineering.rflp import render_rflp_svg
from rflp_lite.methodology.contracts import FailureStage, Phase
from rflp_lite.methodology.gates import global_gate
from rflp_lite.methodology.coverage_matrix import build_requirement_coverage
from rflp_lite.retrieval.planner import KnowledgeGap
from rflp_lite.interface.web.resource_pages import (
    _gate_payload,
    _issue_payload,
    _plain,
    build_analysis_view,
    build_trace_view,
    remember_repair,
    remember_run,
)


resource_api = APIRouter(tags=["AI4MBSE Harness"])
_NON_SEMANTIC_FAILURE_VALUES = frozenset(
    stage.value for stage in (
        FailureStage.STRUCTURAL,
        FailureStage.COMPILER,
        FailureStage.TRANSPORT,
        FailureStage.CONCURRENCY,
        FailureStage.INTERNAL,
    )
)


async def _request_json(request: Request):
    return await request.json()


def _services(request: Request):
    services = getattr(request.app.state, "container", None)
    if services is None or services.v2 is None:
        raise RuntimeError("v2 services are not configured")
    return services.v2


def _run_payload(summary) -> Mapping[str, object]:
    raw = _plain(summary)
    data = dict(raw) if isinstance(raw, Mapping) else {}
    run_id = str(data.get("run_id") or data.get("id") or getattr(summary, "run_id", ""))
    project_id = str(data.get("project_id") or getattr(summary, "project_id", ""))
    phase = data.get("phase") or getattr(summary, "phase", Phase.OPERATIONAL)
    status = data.get("status") or getattr(summary, "status", "queued")
    payload = {
        "run_id": run_id,
        "project_id": project_id,
        "phase": _value(phase),
        "status": _value(status),
        "completed_tasks": list(data.get("completed_tasks", getattr(summary, "completed_tasks", ()))),
        "diagnostics": list(data.get("diagnostics", getattr(summary, "diagnostics", ()))),
    }
    failure_stage = data.get("failure_stage", getattr(summary, "failure_stage", None))
    if failure_stage:
        payload["failure_stage"] = _value(failure_stage)
    for key in ("phase_results", "gate_results", "closure", "current_task", "repair", "runtime"):
        if key in data:
            payload[key] = data[key]
    return payload


def _attach_runtime_metadata(run: Mapping[str, object], analysis) -> Mapping[str, object]:
    runner = getattr(analysis, "runner", None)
    selection = getattr(runner, "runtime_selection", None)
    if selection is None:
        selection = getattr(analysis, "runtime_selection", None)
    if selection is None:
        return run
    run.update(
        {
            "model_profile": str(getattr(selection, "profile_id", "")),
            "provider_id": str(getattr(selection, "provider_id", "")),
            "model_id": str(getattr(selection, "model_id", "")),
            "runtime_mode": str(getattr(selection, "mode", "")),
        }
    )
    run["runtime"] = {
        "profile_id": run["model_profile"],
        "provider_id": run["provider_id"],
        "model_id": run["model_id"],
        "mode": run["runtime_mode"],
    }
    return run


def _attach_deliverable_metadata(
    run: Mapping[str, object],
    services,
    project_id: str,
) -> Mapping[str, object]:
    """Bind an analysis response to the exact package produced from its graph."""

    package = services.deliverables(project_id).build(project_id)
    deliverable = {
        "format": package["format"],
        "project_id": package["project_id"],
        "revision": package["revision"],
        "snapshot_hash": package["snapshot_hash"],
        "manifest": package["manifest"],
        "json_url": f"/projects/{project_id}/deliverables",
        "download_url": f"/projects/{project_id}/deliverables/download",
    }
    return {**run, "deliverable": deliverable}


def _value(value: object, default: str = "") -> str:
    return str(getattr(value, "value", value or default))


def _analysis_service(request: Request, project_id: str):
    """Load the application service, with a narrow bridge for an older runner."""

    services = _services(request)
    try:
        return services.analysis(project_id)
    except TypeError as exc:
        # A partially upgraded local checkout can have the runtime factory
        # wired before WorkflowRunner accepts its metadata. Keep Web usable
        # without editing that user's in-progress application change.
        if "runtime_selection" not in str(exc):
            raise
        from rflp_lite.application.analysis_service import AnalysisService
        from rflp_lite.methodology.workflow import NoopRuntime, WorkflowRunner

        repository = services.repository(project_id)
        runtime = getattr(services, "runtime", None)
        factory = getattr(services, "runtime_factory", None)
        if factory is not None:
            try:
                selection = factory.select(services.settings.active_config(), runtime_override=getattr(services, "_runtime_override", None))
            except TypeError:
                selection = factory.select(services.settings.active_config())
            runtime = getattr(selection, "runtime", runtime)
        return AnalysisService(WorkflowRunner(repository, repository, runtime or NoopRuntime()))


def _call_run(analysis, project_id: str, phase: Phase, run_id: str | None = None, *, force_run: bool = False):
    if run_id is None and not force_run:
        return analysis.run(project_id, phase)
    runner = getattr(analysis, "runner", None)
    if runner is not None and callable(getattr(runner, "run", None)):
        try:
            return runner.run(project_id, phase, run_id=run_id, force_run=force_run)
        except TypeError as exc:
            if "force_run" not in str(exc):
                raise
            return runner.run(project_id, phase, run_id=run_id)
    try:
        return analysis.run(project_id, phase, run_id=run_id, force_run=force_run)
    except TypeError as exc:
        if "run_id" not in str(exc) and "force_run" not in str(exc):
            raise
        return analysis.run(project_id, phase)


def _pipeline_fallback(analysis, project_id: str, *, requested_run_id: str | None, force_run: bool) -> Mapping[str, object]:
    pipeline_id = requested_run_id or f"pipeline-{uuid4().hex[:16]}"
    phase_results: list[Mapping[str, object]] = []
    gate_results: list[Mapping[str, object]] = []
    diagnostics: list[str] = []
    all_passed = True
    blocked_reason = ""
    for phase in (Phase.OPERATIONAL, Phase.FUNCTIONAL, Phase.LOGICAL_PHYSICAL, Phase.ASSURANCE):
        phase_run_id = f"{pipeline_id}-{phase.value}" if force_run else None
        if blocked_reason:
            phase_payload = {
                "run_id": phase_run_id or "",
                "project_id": project_id,
                "phase": phase.value,
                "status": "blocked",
                "completed_tasks": [],
                "diagnostics": [blocked_reason],
            }
            phase_results.append(phase_payload)
            continue
        try:
            summary = _call_run(analysis, project_id, phase, phase_run_id, force_run=force_run)
            phase_payload = _run_payload(summary)
        except Exception as exc:
            phase_payload = {
                "run_id": phase_run_id or "",
                "project_id": project_id,
                "phase": phase.value,
                "status": "failed",
                "completed_tasks": [],
                "diagnostics": [f"{phase.value}: {exc}"],
            }
        phase_payload["phase"] = phase.value
        phase_results.append(phase_payload)
        diagnostics.extend(str(item) for item in phase_payload.get("diagnostics", ()))
        failure_stage = str(phase_payload.get("failure_stage", ""))
        if failure_stage in _NON_SEMANTIC_FAILURE_VALUES:
            all_passed = False
            blocked_reason = f"Blocked by {phase.value} {failure_stage} failure"
            continue
        try:
            gate = _gate_payload(analysis.gate(project_id, phase), fallback_phase=phase)
        except Exception as exc:
            gate = {
                "gate_id": f"{phase.value}-Gate",
                "passed": False,
                "status": "failed",
                "issues": [{"code": "gate_unavailable", "message": str(exc), "severity": "error"}],
                "rollback_phase": phase.value,
            }
        gate["phase"] = phase.value
        gate_results.append(gate)
        if not gate["passed"] or phase_payload["status"] not in {"completed", "complete"}:
            all_passed = False
    global_result = next((item for item in gate_results if item["gate_id"] == "Global-Gate"), None)
    if global_result is None:
        try:
            global_result = _gate_payload(analysis.gate(project_id, Phase.CLOSURE), fallback_phase=Phase.ASSURANCE)
        except Exception:
            global_result = _gate_payload(global_gate(_services_from_analysis(analysis, project_id)), fallback_phase=Phase.ASSURANCE)
        global_result["phase"] = Phase.CLOSURE.value
        gate_results.append(global_result)
    closure: Mapping[str, object]
    if all_passed and global_result["passed"]:
        try:
            closure_summary = _call_run(analysis, project_id, Phase.CLOSURE, f"{pipeline_id}-closure" if force_run else None, force_run=force_run)
            closure_payload = _run_payload(closure_summary)
            phase_results.append(closure_payload)
            closure = {"status": closure_payload["status"], "accepted_revision": None, "manifest": None}
        except Exception as exc:
            diagnostics.append(f"closure: {exc}")
            phase_results.append({"phase": Phase.CLOSURE.value, "status": "failed", "diagnostics": [str(exc)], "completed_tasks": []})
            closure = {"status": "failed", "accepted_revision": None, "manifest": None, "diagnostics": [str(exc)]}
    else:
        phase_results.append({"phase": Phase.CLOSURE.value, "status": "blocked", "diagnostics": ["Global Gate must pass before Closure"], "completed_tasks": []})
        closure = {"status": "blocked", "accepted_revision": None, "manifest": None}
        diagnostics.append("Global Gate must pass before Closure")
    return {
        "run_id": pipeline_id,
        "project_id": project_id,
        "phase": Phase.CLOSURE.value,
        "status": "completed" if all_passed and global_result["passed"] else "degraded",
        "completed_tasks": [task for item in phase_results for task in item.get("completed_tasks", ())],
        "diagnostics": diagnostics,
        "phase_results": phase_results,
        "gate_results": gate_results,
        "closure": closure,
        "force_run": force_run,
        "mode": "pipeline",
    }


def _services_from_analysis(analysis, project_id: str):
    # This path is only used by the defensive fallback above; normal runs use
    # AnalysisService.gate, which preserves the application's gate adapter.
    return analysis.runner.model_repository.load_graph(project_id)


def _orchestrator_payload(analysis, project_id: str, result, *, force_run: bool) -> Mapping[str, object]:
    payload = _run_payload(result)
    phase_order = [phase.value for phase, _label in ((Phase.OPERATIONAL, ""), (Phase.FUNCTIONAL, ""), (Phase.LOGICAL_PHYSICAL, ""), (Phase.ASSURANCE, ""), (Phase.CLOSURE, ""))]
    result_phase = str(payload.get("phase", Phase.OPERATIONAL.value))
    result_status = str(payload.get("status", "degraded"))
    failure_stage = str(payload.get("failure_stage", ""))
    dependency_blocked = (
        result_status not in {"completed", "complete"}
        and failure_stage in _NON_SEMANTIC_FAILURE_VALUES
    )
    try:
        result_index = phase_order.index(result_phase)
    except ValueError:
        result_index = 0
    phase_results = [
        {
            "phase": phase,
            "status": "completed" if index < result_index and result_status == "completed" else result_status if index == result_index else "blocked" if dependency_blocked else "pending",
            "completed_tasks": list(payload.get("completed_tasks", ())) if index == result_index else [],
            "diagnostics": list(payload.get("diagnostics", ())) if index == result_index else [f"Blocked by {failure_stage} failure"] if dependency_blocked and index > result_index else [],
        }
        for index, phase in enumerate(phase_order)
    ]
    gate_results: list[Mapping[str, object]] = []
    for phase in (Phase.OPERATIONAL, Phase.FUNCTIONAL, Phase.LOGICAL_PHYSICAL, Phase.ASSURANCE, Phase.CLOSURE):
        try:
            gate = _gate_payload(analysis.gate(project_id, phase), fallback_phase=phase)
        except Exception as exc:
            gate = {"gate_id": f"{phase.value}-Gate", "passed": False, "status": "failed", "issues": [], "rollback_phase": phase.value, "message": str(exc)}
        gate["phase"] = phase.value
        gate_results.append(gate)
    global_result = next((item for item in gate_results if item["gate_id"] == "Global-Gate"), gate_results[-1])
    closure_status = "completed" if result_phase == Phase.CLOSURE.value and result_status == "completed" else "blocked"
    payload.update(
        {
            "mode": "pipeline",
            "force_run": force_run,
            "phase_results": phase_results,
            "gate_results": gate_results,
            "closure": {"status": closure_status, "accepted_revision": None, "manifest": None},
        }
    )
    if not payload.get("diagnostics") and not global_result["passed"]:
        payload["diagnostics"] = ["Global Gate has not passed"]
    return payload


def _invoke_pipeline(analysis, project_id: str, *, run_id: str | None, force_run: bool) -> Mapping[str, object]:
    pipeline = getattr(analysis, "run_pipeline", None)
    if callable(pipeline):
        try:
            result = pipeline(project_id, run_id=run_id, force_run=force_run)
        except TypeError as exc:
            if "force_run" not in str(exc) and "run_id" not in str(exc):
                raise
            result = pipeline(project_id)
        payload = _run_payload(result)
        payload["mode"] = "pipeline"
        payload["force_run"] = force_run
        return payload
    orchestrator = getattr(getattr(analysis, "runner", None), "orchestrator", None)
    if callable(getattr(orchestrator, "run", None)):
        try:
            result = orchestrator.run(project_id, run_id=run_id, force_new=force_run)
        except TypeError as exc:
            if "force_new" not in str(exc):
                raise
            result = orchestrator.run(project_id, run_id=run_id, force_run=force_run)
        return _orchestrator_payload(analysis, project_id, result, force_run=force_run)
    return _pipeline_fallback(analysis, project_id, requested_run_id=run_id, force_run=force_run)


def _profile_test_payload(settings, raw: object) -> Mapping[str, object]:
    if not isinstance(raw, Mapping):
        raise ContractViolation("model profile test payload must be an object")
    payload = dict(raw)
    profile_id = str(payload.get("profile_id") or payload.get("id") or "").strip()
    if not profile_id:
        raise ContractViolation("profile_id is required")
    if "id" not in payload:
        snapshot = settings.list_profiles()
        profile = next((item for item in snapshot.get("profiles", ()) if isinstance(item, Mapping) and item.get("id") == profile_id), None)
        if profile is None:
            raise ContractViolation(f"LLM profile not found: {profile_id}")
        payload.update(profile)
    payload["id"] = profile_id
    return payload


def _connection_failure(exc: AdapterFailure) -> Mapping[str, object]:
    """Convert provider errors into safe, actionable UI status metadata."""

    detail = str(exc)
    if "缺少 API Key" in detail:
        status = "not_configured"
        message = "远程模型尚未配置 API Key。"
    elif "HTTP 401" in detail or "HTTP 403" in detail:
        status = "authentication_failed"
        message = "模型服务认证失败，请检查 API Key。"
    elif "HTTP " in detail:
        status = "rejected"
        message = "模型服务拒绝了连接测试。"
    elif "返回不是有效 JSON" in detail or "返回为空" in detail:
        status = "invalid_response"
        message = "模型服务返回格式无效或为空。"
    else:
        status = "unreachable"
        message = "无法连接到模型服务，请确认 Base URL、服务状态和防火墙设置。"
    return {"connected": False, "connection_status": status, "status_code": None, "message": message}


def _resolve_repair_issue(request: Request, project_id: str, issue_id: str, analysis):
    services = _services(request)
    repository = services.repository(project_id)
    stored = list(services.model(project_id).issues(project_id))
    exact = next((item for item in stored if str(item.get("id")) == issue_id), None)
    if exact is not None:
        return issue_id, _issue_payload(exact)
    view = build_analysis_view(request, project_id)
    issue = next((item for item in view["issues"] if str(item.get("id")) == issue_id), None)
    if issue is None:
        raise ContractViolation(f"repair requires a registered issue: {issue_id}")
    phase_value = str(issue.get("rollback_phase") or Phase.ASSURANCE.value)
    try:
        phase = Phase(phase_value)
    except ValueError:
        phase = Phase.ASSURANCE
    # GET computes gate issues without writes. Materialize the selected issue
    # through the existing gate adapter so the legacy repair use case can own it.
    try:
        analysis.gate(project_id, phase)
    except Exception:
        pass
    stored = list(services.model(project_id).issues(project_id))
    matching = next(
        (
            item for item in stored
            if str(item.get("code")) == str(issue["code"])
            and tuple(str(value) for value in item.get("entity_ids", ())) == tuple(issue.get("entity_ids", ()))
        ),
        None,
    )
    if matching is None:
        saver = getattr(repository, "save_issue", None)
        if not callable(saver):
            raise ContractViolation(f"repair issue cannot be persisted: {issue_id}")
        saver(project_id, {
            "id": issue_id,
            "code": issue["code"],
            "severity": issue["severity"],
            "entity_ids": issue["entity_ids"],
            "suggested_rollback": phase.value,
        })
        matching = {**issue, "id": issue_id}
    return str(matching.get("id")), _issue_payload(matching)


def _error(exc: Exception) -> JSONResponse:
    from rflp_lite.domain.errors import ConflictError
    status = 404 if isinstance(exc, NotFoundError) else 409 if isinstance(exc, (ConcurrentModificationError, ConflictError)) else 422
    return JSONResponse({"status": "failed", "error": type(exc).__name__, "message": str(exc)}, status_code=status)


def _flag(value: object) -> bool:
    return str(value or "").casefold() in {"1", "true", "yes", "on"}


def _expected_revision(payload: Mapping[str, object]) -> int | None:
    value = payload.get("expected_revision")
    return int(value) if value is not None and str(value).strip() else None


async def _json_object(request: Request) -> Mapping[str, object]:
    raw = await request.body()
    payload = json.loads(raw.decode("utf-8")) if raw else {}
    if payload is None:
        return {}
    if not isinstance(payload, Mapping):
        raise ContractViolation("request payload must be an object")
    return payload


@resource_api.get("/projects")
def list_projects(request: Request):
    return {"status": "ok", "projects": [{"id": item.name, "path": str(item.path)} for item in _services(request).projects.list()]}


@resource_api.post("/projects")
async def create_project(request: Request):
    try:
        payload = await request.json()
        if not isinstance(payload, Mapping):
            raise ContractViolation("project payload must be an object")
        project_id = str(payload.get("id", payload.get("name", ""))).strip()
        if not project_id:
            raise ContractViolation("project id is required")
        return {"status": "ok", "project": _services(request).projects.create(project_id, str(payload.get("name", project_id)))}
    except (ContractViolation, RflpError, OSError, ValueError) as exc:
        return _error(exc)


@resource_api.delete("/projects/{project_id}")
def delete_project(request: Request, project_id: str):
    try:
        return {"status": "ok", **_services(request).delete_project(project_id)}
    except (ContractViolation, RflpError, OSError, ValueError) as exc:
        return _error(exc)


@resource_api.post("/projects/{project_id}/requirements")
async def add_requirement(request: Request, project_id: str):
    try:
        payload = json.loads((await request.body()).decode("utf-8"))
        if not isinstance(payload, Mapping):
            raise ContractViolation("requirement payload must be an object")
        result = _services(request).projects.add_requirement(project_id, str(payload.get("text", "")))
        return {"status": "ok", **result}
    except (ContractViolation, RflpError, OSError, ValueError) as exc:
        return _error(exc)


@resource_api.post("/projects/{project_id}/goal")
async def set_project_goal(request: Request, project_id: str):
    try:
        payload = await _json_object(request)
        result = _services(request).context(project_id).set_goal(str(payload.get("text", payload.get("goal", ""))))
        return {"status": "ok", "context": result}
    except (ContractViolation, RflpError, OSError, ValueError) as exc:
        return _error(exc)


@resource_api.get("/projects/{project_id}/context")
def get_project_context(request: Request, project_id: str):
    try:
        graph = _services(request).model(project_id).graph(project_id)
        system = next(
            (
                item for item in graph.entities
                if item.kind is EntityKind.SYSTEM and item.meta.status.value != "deprecated"
            ),
            None,
        )
        goals = [
            str(item.payload.get("goal_text", item.meta.name))
            for item in graph.entities
            if item.kind is EntityKind.REQUIREMENT
            and item.meta.status.value != "deprecated"
            and item.payload.get("source") == "user_goal"
        ]
        return {
            "status": "ok",
            "context": {
                "project_id": project_id,
                "revision": graph.revision,
                "goal": str(system.payload.get("mission", "")) if system else "",
                "goals": list(dict.fromkeys(goals)),
                "system_id": system.id if system else None,
            },
        }
    except (ContractViolation, RflpError, OSError, ValueError) as exc:
        return _error(exc)


@resource_api.post("/projects/{project_id}/documents")
async def ingest_document(request: Request, project_id: str):
    try:
        content_type = request.headers.get("content-type", "").casefold()
        if content_type.startswith("multipart/form-data"):
            form = await request.form()
            upload = form.get("file")
            if upload is None or (not isinstance(upload, UploadFile) and not hasattr(upload, "read")):
                raise ContractViolation("multipart document field 'file' is required")
            result = _services(request).projects.ingest_uploaded(project_id, upload.filename or "upload", await upload.read())
        else:
            payload = await request.json()
            if not isinstance(payload, Mapping) or not payload.get("path"):
                raise ContractViolation("document path is required")
            result = _services(request).projects.ingest(project_id, Path(str(payload["path"])))
        return {"status": "ok", "document": result}
    except (ContractViolation, RflpError, OSError, ValueError) as exc:
        return _error(exc)


@resource_api.post("/projects/{project_id}/analysis")
async def run_analysis(request: Request, project_id: str):
    try:
        payload = await request.json()
        if payload is not None and not isinstance(payload, Mapping):
            raise ContractViolation("analysis payload must be an object")
        payload = payload if isinstance(payload, Mapping) else {}
        mode = str(payload.get("mode", "generate" if "phase" not in payload else "phase")).casefold()
        force_run = bool(payload.get("force_run", False))
        requested_run_id = str(payload.get("run_id", "")).strip() or None
        requirement_text = str(payload.get("requirement_text", "")).strip() or None
        goal = str(payload.get("goal", "")).strip() or None
        document_ids = tuple(
            str(item) for item in payload.get("document_ids", ()) if str(item).strip()
        )
        if goal:
            _services(request).context(project_id).set_goal(goal)
        if not _services(request).projects.has_analysis_input(project_id) and not (
            mode in {"generate", "vertical", "pipeline"} and (requirement_text or document_ids)
        ):
            raise InputRequired("submit a requirement or ingest a document before analysis")
        if force_run and requested_run_id is None:
            requested_run_id = f"web-run-{uuid4().hex[:16]}"
        if mode in {"generate", "vertical"}:
            generation = _services(request).generation(project_id)
            result = generation.generate(
                project_id,
                requirement_text=requirement_text,
                document_ids=document_ids,
                run_id=requested_run_id,
                force_new=force_run,
            )
            run = result.as_dict()
            run["mode"] = "generate"
            run["force_run"] = force_run
            _attach_runtime_metadata(run, generation)
        else:
            analysis = _analysis_service(request, project_id)
        if mode == "pipeline":
            input_service = _services(request).requirements_input(project_id)
            if requirement_text:
                input_service.ensure_text_requirements(requirement_text)
            elif document_ids:
                input_service.ensure_document_requirements(document_ids)
            run = _invoke_pipeline(analysis, project_id, run_id=requested_run_id, force_run=force_run)
        elif mode not in {"generate", "vertical"}:
            phase = Phase(str(payload.get("phase", Phase.OPERATIONAL.value)))
            run = _run_payload(_call_run(analysis, project_id, phase, requested_run_id, force_run=force_run))
            run["mode"] = "phase"
            run["force_run"] = force_run
            _attach_runtime_metadata(run, analysis)
        run = _attach_deliverable_metadata(run, _services(request), project_id)
        remember_run(request, project_id, run)
        return {"status": "ok", "run": run}
    except (ContractViolation, RflpError, OSError, ValueError) as exc:
        return _error(exc)


@resource_api.get("/projects/{project_id}/analysis")
def get_analysis(request: Request, project_id: str):
    try:
        view = build_analysis_view(request, project_id)
        return {"status": "ok", "analysis": view, **view}
    except (ContractViolation, RflpError, OSError, ValueError) as exc:
        return _error(exc)


@resource_api.get("/projects/{project_id}/controller")
def get_controller_plan(request: Request, project_id: str):
    try:
        controller = _services(request).generation(project_id).controller_plan(project_id)
        return {"status": "ok", "controller": controller}
    except (ContractViolation, RflpError, OSError, ValueError) as exc:
        return _error(exc)


@resource_api.post("/projects/{project_id}/controller/execute")
async def execute_controller_action(request: Request, project_id: str):
    try:
        payload = await _json_object(request)
        action_id = str(payload.get("action_id", "")).strip() or None
        option_id = str(payload.get("option_id", "")).strip() or None
        result = _services(request).generation(project_id).execute_controller_action(
            project_id,
            action_id=action_id,
            option_id=option_id,
            expected_revision=_expected_revision(payload),
        )
        return {"status": "ok", "controller": result}
    except (ContractViolation, RflpError, OSError, ValueError) as exc:
        return _error(exc)


@resource_api.post("/projects/{project_id}/controller/iterate")
async def iterate_controller(request: Request, project_id: str):
    try:
        payload = await _json_object(request)
        max_iterations = int(payload.get("max_iterations", 3))
        result = _services(request).generation(project_id).iterate_controller(
            project_id,
            max_iterations=max_iterations,
            expected_revision=_expected_revision(payload),
        )
        return {"status": "ok", "controller": result}
    except (ContractViolation, RflpError, OSError, ValueError) as exc:
        return _error(exc)


@resource_api.get("/projects/{project_id}/runs/{run_id}")
def get_run(request: Request, project_id: str, run_id: str):
    try:
        run = _services(request).repository(project_id).load_run(project_id, run_id)
        if run is None:
            raise ContractViolation(f"run not found: {run_id}")
        return {"status": "ok", "run": asdict(run)}
    except (ContractViolation, RflpError, OSError, ValueError) as exc:
        return _error(exc)


@resource_api.get("/projects/{project_id}/model")
def get_model(request: Request, project_id: str):
    try:
        graph = _services(request).model(project_id).graph(project_id)
        return {"status": "ok", "revision": graph.revision, "graph_hash": graph.snapshot_hash, "entities": [item.as_dict() for item in graph.entities], "relations": [asdict(item) for item in graph.relations]}
    except (ContractViolation, RflpError, OSError, ValueError) as exc:
        return _error(exc)


@resource_api.get("/projects/{project_id}/trace")
def get_trace(request: Request, project_id: str):
    try:
        trace = build_trace_view(request, project_id)
        return {"status": "ok", "trace": trace, **trace}
    except (ContractViolation, RflpError, OSError, ValueError) as exc:
        return _error(exc)


@resource_api.get("/projects/{project_id}/coverage")
def get_coverage(request: Request, project_id: str):
    try:
        graph = _services(request).model(project_id).graph(project_id)
        matrix = build_requirement_coverage(graph)
        return {"status": "ok", "project_id": project_id, "revision": graph.revision, "graph_hash": graph.snapshot_hash, **matrix.as_dict()}
    except (ContractViolation, RflpError, OSError, ValueError) as exc:
        return _error(exc)


@resource_api.get("/projects/{project_id}/requirements")
def get_requirements(
    request: Request,
    project_id: str,
    status: str | None = None,
    level: str | None = None,
    type: str | None = None,
    producer: str | None = None,
    has_issue: str | None = None,
    missing_trace: str | None = None,
    missing_verification: str | None = None,
    q: str | None = None,
):
    try:
        services = _services(request)
        view = build_requirements_view(services.model(project_id).graph(project_id), tuple(services.model(project_id).issues(project_id)))
        rows = list(view["rows"])
        query = str(q or "").casefold().strip()
        rows = [row for row in rows if (not status or row["status"] == status) and (not level or row["level"] == level) and (not type or row["type"] == type) and (not producer or row["producer"] == producer) and (_flag(has_issue) is False or row["issue_count"] > 0) and (_flag(missing_trace) is False or row["trace_status"] != "PASS") and (_flag(missing_verification) is False or row["verification_count"] == 0) and (not query or query in str(row["name"]).casefold() or query in str(row["statement"]).casefold() or query in str(row["id"]).casefold())]
        view["rows"] = rows
        view["filtered_count"] = len(rows)
        return {"status": "ok", "requirements": view, **view}
    except (ContractViolation, RflpError, OSError, ValueError) as exc:
        return _error(exc)


@resource_api.get("/projects/{project_id}/requirements/{entity_id}")
def get_requirement_detail(request: Request, project_id: str, entity_id: str):
    try:
        services = _services(request)
        detail = build_requirement_detail(services.model(project_id).graph(project_id), entity_id, issues=tuple(services.model(project_id).issues(project_id)), evidence=tuple(services.evidence(project_id).list(project_id)))
        if detail is None:
            raise NotFoundError(f"requirement not found: {entity_id}")
        return {"status": "ok", "requirement": detail, **detail}
    except (ContractViolation, RflpError, OSError, ValueError) as exc:
        return _error(exc)


@resource_api.get("/projects/{project_id}/traceability")
def get_traceability(request: Request, project_id: str):
    try:
        services = _services(request)
        view = build_traceability_view(services.model(project_id).graph(project_id), tuple(services.model(project_id).issues(project_id)))
        return {"status": "ok", "traceability": view, **view}
    except (ContractViolation, RflpError, OSError, ValueError) as exc:
        return _error(exc)


def _rflp_payload(request: Request, project_id: str, *, selected_requirement: str | None = None, kind: str | None = None, status: str | None = None, issue_only: str | None = None, accepted_only: str | None = None) -> Mapping[str, object]:
    services = _services(request)
    return build_rflp_view(services.model(project_id).graph(project_id), tuple(services.model(project_id).issues(project_id)), selected_requirement=selected_requirement, kind=kind, status=status, issue_only=_flag(issue_only), accepted_only=_flag(accepted_only))


@resource_api.get("/projects/{project_id}/rflp")
def get_rflp(request: Request, project_id: str, requirement_id: str | None = None, kind: str | None = None, status: str | None = None, issue_only: str | None = None, accepted_only: str | None = None):
    try:
        view = _rflp_payload(request, project_id, selected_requirement=requirement_id, kind=kind, status=status, issue_only=issue_only, accepted_only=accepted_only)
        return {"status": "ok", "rflp": view, **view}
    except (ContractViolation, RflpError, OSError, ValueError) as exc:
        return _error(exc)


@resource_api.get("/projects/{project_id}/rflp/trace/{requirement_id}")
def get_rflp_trace(request: Request, project_id: str, requirement_id: str):
    try:
        view = _rflp_payload(request, project_id, selected_requirement=requirement_id)
        if requirement_id not in {str(node["id"]) for node in view["nodes"]}:
            raise NotFoundError(f"requirement not found: {requirement_id}")
        return {"status": "ok", "rflp": view, **view}
    except (ContractViolation, RflpError, OSError, ValueError) as exc:
        return _error(exc)


@resource_api.get("/projects/{project_id}/rflp.svg")
def get_rflp_svg(request: Request, project_id: str, requirement_id: str | None = None):
    try:
        return Response(content=render_rflp_svg(_rflp_payload(request, project_id, selected_requirement=requirement_id)), media_type="image/svg+xml")
    except (ContractViolation, RflpError, OSError, ValueError) as exc:
        return _error(exc)


@resource_api.get("/projects/{project_id}/operational")
def get_operational(request: Request, project_id: str):
    try:
        services = _services(request)
        view = build_operational_view(services.model(project_id).graph(project_id), tuple(services.model(project_id).issues(project_id)))
        return {"status": "ok", "operational": view, **view}
    except (ContractViolation, RflpError, OSError, ValueError) as exc:
        return _error(exc)


@resource_api.get("/projects/{project_id}/behavior")
def get_behavior(request: Request, project_id: str):
    try:
        services = _services(request)
        view = build_behavior_view(services.model(project_id).graph(project_id), tuple(services.model(project_id).issues(project_id)))
        return {"status": "ok", "behavior": view, **view}
    except (ContractViolation, RflpError, OSError, ValueError) as exc:
        return _error(exc)


@resource_api.get("/projects/{project_id}/assurance")
def get_assurance(request: Request, project_id: str):
    try:
        services = _services(request)
        view = build_assurance_view(services.model(project_id).graph(project_id), tuple(services.model(project_id).issues(project_id)))
        return {"status": "ok", "assurance": view, **view}
    except (ContractViolation, RflpError, OSError, ValueError) as exc:
        return _error(exc)


@resource_api.get("/projects/{project_id}/history")
def get_history(request: Request, project_id: str):
    try:
        view = build_history_view(_services(request).repository(project_id), project_id)
        return {"status": "ok", "history": view, **view}
    except (ContractViolation, RflpError, OSError, ValueError) as exc:
        return _error(exc)


@resource_api.get("/projects/{project_id}/revisions/{revision}/diff")
def get_revision_diff(request: Request, project_id: str, revision: int):
    try:
        repository = _services(request).repository(project_id)
        after = repository.load_revision(project_id, revision)
        if after is None:
            raise NotFoundError(f"revision not found: {revision}")
        before = repository.load_revision(project_id, revision - 1)
        return {"status": "ok", "diff": build_revision_diff(before, after, revision=revision)}
    except (ContractViolation, RflpError, OSError, ValueError) as exc:
        return _error(exc)


@resource_api.get("/projects/{project_id}/entities")
def list_entities(request: Request, project_id: str, kind: str | None = None):
    try:
        parsed_kind = EntityKind(kind) if kind else None
        return {"status": "ok", "entities": [item.as_dict() for item in _services(request).model(project_id).entities(project_id, parsed_kind)]}
    except (ContractViolation, RflpError, OSError, ValueError) as exc:
        return _error(exc)


@resource_api.patch("/projects/{project_id}/entities/{entity_id}")
async def patch_entity(request: Request, project_id: str, entity_id: str):
    try:
        payload = await request.json()
        if not isinstance(payload, Mapping):
            raise ContractViolation("entity patch must be an object")
        expected_revision = int(payload.get("expected_revision", -1))
        fields = payload.get("field_patch", payload.get("fields", {}))
        if not isinstance(fields, Mapping):
            raise ContractViolation("field_patch must be an object")
        graph = _services(request).model(project_id).graph(project_id)
        patch = Patch.create(project_id, "user.entity_patch", (UpdateEntity(entity_id, fields),), "user entity edit", expected_revision)
        revision = _services(request).model(project_id).apply_patch(project_id, patch, expected_revision)
        return {"status": "ok", "revision": asdict(revision)}
    except (ContractViolation, RflpError, OSError, ValueError) as exc:
        return _error(exc)


async def _run_review_command(request: Request, project_id: str, entity_id: str, action: str):
    payload = await _json_object(request)
    service = _services(request).review(project_id)
    expected = _expected_revision(payload)
    if action == "accept":
        result = service.accept_entity(project_id, entity_id, expected_revision=expected)
    elif action == "reject":
        result = service.reject_entity(project_id, entity_id, expected_revision=expected)
    elif action == "lock":
        result = service.lock_entity(project_id, entity_id, expected_revision=expected)
    elif action == "unlock":
        result = service.unlock_entity(project_id, entity_id, expected_revision=expected)
    elif action == "edit":
        raw_payload = payload.get("payload")
        if raw_payload is not None and not isinstance(raw_payload, Mapping):
            raise ContractViolation("payload must be an object")
        result = service.edit_entity(project_id, entity_id, statement=str(payload["statement"]) if payload.get("statement") is not None else None, name=str(payload["name"]) if payload.get("name") is not None else None, payload=dict(raw_payload) if isinstance(raw_payload, Mapping) else None, expected_revision=expected)
    elif action == "reanalyze":
        return {"status": "ok", "reanalysis": service.request_reanalysis(project_id, entity_id, expected_revision=expected)}
    else:
        raise ContractViolation(f"unsupported review action: {action}")
    return {"status": "ok", "review": result.as_dict(), "revision": result.revision}


@resource_api.post("/projects/{project_id}/entities/{entity_id}/accept")
async def accept_entity(request: Request, project_id: str, entity_id: str):
    try:
        return await _run_review_command(request, project_id, entity_id, "accept")
    except (ContractViolation, RflpError, OSError, ValueError) as exc:
        return _error(exc)


@resource_api.post("/projects/{project_id}/entities/{entity_id}/reject")
async def reject_entity(request: Request, project_id: str, entity_id: str):
    try:
        return await _run_review_command(request, project_id, entity_id, "reject")
    except (ContractViolation, RflpError, OSError, ValueError) as exc:
        return _error(exc)


@resource_api.post("/projects/{project_id}/entities/{entity_id}/lock")
async def lock_entity(request: Request, project_id: str, entity_id: str):
    try:
        return await _run_review_command(request, project_id, entity_id, "lock")
    except (ContractViolation, RflpError, OSError, ValueError) as exc:
        return _error(exc)


@resource_api.post("/projects/{project_id}/entities/{entity_id}/unlock")
async def unlock_entity(request: Request, project_id: str, entity_id: str):
    try:
        return await _run_review_command(request, project_id, entity_id, "unlock")
    except (ContractViolation, RflpError, OSError, ValueError) as exc:
        return _error(exc)


@resource_api.post("/projects/{project_id}/entities/{entity_id}/edit")
async def edit_entity(request: Request, project_id: str, entity_id: str):
    try:
        return await _run_review_command(request, project_id, entity_id, "edit")
    except (ContractViolation, RflpError, OSError, ValueError) as exc:
        return _error(exc)


@resource_api.post("/projects/{project_id}/entities/{entity_id}/continue")
async def continue_entity_generation(request: Request, project_id: str, entity_id: str):
    try:
        payload = await _json_object(request)
        decision = payload.get("controller_decision")
        if decision is not None and not isinstance(decision, Mapping):
            raise ContractViolation("controller_decision must be an object")
        result = _services(request).generation(project_id).continue_generation(
            project_id,
            entity_id,
            expected_revision=_expected_revision(payload),
            controller_decision=dict(decision) if isinstance(decision, Mapping) else None,
        )
        return {"status": "ok", "continuation": result}
    except (ContractViolation, RflpError, OSError, ValueError) as exc:
        return _error(exc)


@resource_api.post("/projects/{project_id}/entities/{entity_id}/reanalyze")
async def request_entity_reanalysis(request: Request, project_id: str, entity_id: str):
    try:
        return await _run_review_command(request, project_id, entity_id, "reanalyze")
    except (ContractViolation, RflpError, OSError, ValueError) as exc:
        return _error(exc)


@resource_api.post("/projects/{project_id}/entities/{entity_id}/reanalyze/execute")
async def execute_entity_reanalysis(request: Request, project_id: str, entity_id: str):
    try:
        payload = await _json_object(request)
        expected = _expected_revision(payload)
        result = _services(request).generation(project_id).reanalyze(
            project_id,
            entity_id,
            expected_revision=expected,
        )
        return {"status": "ok", "reanalysis": result}
    except (ContractViolation, RflpError, OSError, ValueError) as exc:
        return _error(exc)


@resource_api.get("/projects/{project_id}/views/{view_id}")
def get_view(request: Request, project_id: str, view_id: str):
    try:
        return {"status": "ok", "view": _services(request).render(project_id).view(project_id, view_id).as_dict()}
    except (ContractViolation, RflpError, OSError, ValueError) as exc:
        return _error(exc)


@resource_api.get("/projects/{project_id}/evidence")
def list_evidence(request: Request, project_id: str):
    try:
        return {"status": "ok", "evidence": list(_services(request).evidence(project_id).list(project_id))}
    except (ContractViolation, RflpError, OSError, ValueError) as exc:
        return _error(exc)


@resource_api.get("/projects/{project_id}/tools")
def list_engineering_tools(request: Request, project_id: str):
    try:
        return {
            "status": "ok",
            "tools": list(_services(request).tools(project_id).list_tools()),
        }
    except (ContractViolation, RflpError, OSError, ValueError) as exc:
        return _error(exc)


@resource_api.post("/projects/{project_id}/evidence/search")
async def search_evidence(request: Request, project_id: str):
    try:
        payload = await _request_json(request)
        if not isinstance(payload, Mapping):
            raise ContractViolation("evidence query must be an object")
        graph = _services(request).model(project_id).graph(project_id)
        from rflp_lite.methodology.context import ContextBuilder
        from rflp_lite.methodology.tasks import tasks_for_phase
        context = ContextBuilder().build(graph, tasks_for_phase(Phase.OPERATIONAL)[0])
        result = _services(request).evidence(project_id).search(KnowledgeGap("api", str(payload.get("query", ""))), context)
        return {"status": "ok", "candidates": [asdict(item) for item in result.candidates], "gaps": [asdict(item) for item in result.gaps], "workflow_blocked": result.workflow_blocked, "confidence": result.confidence}
    except (ContractViolation, RflpError, OSError, ValueError) as exc:
        return _error(exc)


@resource_api.post("/projects/{project_id}/vv/{case_id}/execute")
async def execute_vv(request: Request, project_id: str, case_id: str):
    try:
        payload = await _request_json(request)
        if not isinstance(payload, Mapping):
            raise ContractViolation("V&V execution payload must be an object")
        result = _services(request).vv(project_id).record_result(
            project_id,
            case_id,
            outcome=str(payload.get("outcome", "")),
            claim=str(payload.get("claim", "")),
            excerpt=str(payload.get("excerpt", "")),
            locator=str(payload.get("locator", "")),
            source_type=str(payload.get("source_type", "vv_execution")),
            expected_revision=payload.get("expected_revision"),
            metadata=payload.get("metadata") if isinstance(payload.get("metadata"), Mapping) else None,
        )
        execution = result.as_dict()
        return {"status": "ok", "execution": execution, **execution}
    except (ContractViolation, RflpError, OSError, ValueError) as exc:
        return _error(exc)


@resource_api.post("/projects/{project_id}/vv/{case_id}/tools/{tool_id}/execute")
async def execute_engineering_tool(
    request: Request,
    project_id: str,
    case_id: str,
    tool_id: str,
):
    try:
        payload = await _request_json(request)
        if not isinstance(payload, Mapping):
            raise ContractViolation("engineering tool payload must be an object")
        parameters = payload.get("parameters", {})
        if not isinstance(parameters, Mapping):
            raise ContractViolation("engineering tool parameters must be an object")
        result = _services(request).tools(project_id).execute(
            project_id,
            case_id,
            tool_id,
            parameters=parameters,
            expected_revision=payload.get("expected_revision"),
        )
        tool_execution = result.as_dict()
        return {"status": "ok", "tool_execution": tool_execution, **tool_execution}
    except (ContractViolation, RflpError, OSError, ValueError) as exc:
        return _error(exc)


@resource_api.get("/projects/{project_id}/issues")
def list_issues(request: Request, project_id: str):
    try:
        return {"status": "ok", "issues": list(_services(request).model(project_id).issues(project_id))}
    except (ContractViolation, RflpError, OSError, ValueError) as exc:
        return _error(exc)


@resource_api.post("/projects/{project_id}/repair")
async def repair(request: Request, project_id: str):
    try:
        payload = await request.json()
        if not isinstance(payload, Mapping) or not payload.get("issue_id"):
            raise ContractViolation("issue_id is required")
        issue_id = str(payload["issue_id"])
        analysis = _analysis_service(request, project_id)
        resolved_issue_id, issue_view = _resolve_repair_issue(request, project_id, issue_id, analysis)
        result = _call_repair(analysis, project_id, resolved_issue_id)
        run = _run_payload(result)
        repair_view = {
            "issue_id": issue_id,
            "status": "completed" if run["status"] == "completed" else run["status"],
            "root_cause": issue_view["root_cause"],
            "rollback_phase": issue_view["rollback_phase"] or "—",
            "rollback_task": issue_view["suggested_task"],
            "automatic_round": int(payload.get("automatic_round", 1) or 1),
            "manual_action": "Review the updated Gate and rerun the affected phase if required.",
            "run_id": run["run_id"],
        }
        try:
            phase = Phase(str(issue_view.get("rollback_phase") or Phase.ASSURANCE.value))
        except ValueError:
            phase = Phase.ASSURANCE
        try:
            repair_view["re_gate"] = _gate_payload(analysis.gate(project_id, phase), fallback_phase=phase)
        except Exception as exc:
            repair_view["re_gate"] = {"status": "unavailable", "message": str(exc)}
        run["repair"] = repair_view
        remember_run(request, project_id, run)
        remember_repair(request, project_id, repair_view)
        return {"status": "ok", "run": run, "repair": repair_view}
    except (ContractViolation, RflpError, OSError, ValueError) as exc:
        return _error(exc)


def _call_repair(analysis, project_id: str, issue_id: str):
    return analysis.repair(project_id, issue_id)


@resource_api.post("/projects/{project_id}/export")
async def export_model(request: Request, project_id: str):
    try:
        payload = await request.json()
        view_id = str(payload.get("view_id", "rflp")) if isinstance(payload, Mapping) else "rflp"
        output_format = str(payload.get("format", "json")) if isinstance(payload, Mapping) else "json"
        if output_format.casefold() == "sysml":
            content = graph_sysml(_services(request).model(project_id).graph(project_id)).encode("utf-8")
            media_type = "text/plain"
        else:
            content, media_type = _services(request).render(project_id).export(project_id, view_id, output_format)
        return Response(content=content, media_type=media_type)
    except (ContractViolation, RflpError, OSError, ValueError) as exc:
        return _error(exc)


@resource_api.get("/projects/{project_id}/deliverables")
def get_deliverables(request: Request, project_id: str):
    try:
        package = _services(request).deliverables(project_id).build(project_id)
        return {"status": "ok", "deliverable": package}
    except (ContractViolation, RflpError, OSError, ValueError) as exc:
        return _error(exc)


@resource_api.get("/projects/{project_id}/deliverables/download")
def download_deliverables(request: Request, project_id: str):
    try:
        content, media_type = _services(request).deliverables(project_id).export_zip(project_id)
        filename = f"{project_id}-engineering-deliverables.zip"
        return Response(
            content=content,
            media_type=media_type,
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    except (ContractViolation, RflpError, OSError, ValueError) as exc:
        return _error(exc)


@resource_api.post("/projects/{project_id}/sysml/import")
async def import_sysml(request: Request, project_id: str):
    try:
        text = (await request.body()).decode("utf-8")
        return _append_sysml_import(request, project_id, text)
    except (ContractViolation, RflpError, OSError, UnicodeDecodeError, ValueError) as exc:
        return _error(exc)


@resource_api.post("/projects/{project_id}/sysml/import/upload")
async def upload_sysml(request: Request, project_id: str):
    try:
        form = await request.form()
        upload = form.get("file")
        if upload is None or (not isinstance(upload, UploadFile) and not hasattr(upload, "read")):
            raise ContractViolation("multipart SysML field 'file' is required")
        filename = str(getattr(upload, "filename", "")).casefold()
        if not filename.endswith(".sysml"):
            raise ContractViolation("uploaded SysML file must use the .sysml extension")
        content = await upload.read()
        return _append_sysml_import(request, project_id, content.decode("utf-8"))
    except (ContractViolation, RflpError, OSError, UnicodeDecodeError, ValueError) as exc:
        return _error(exc)


def _append_sysml_import(request: Request, project_id: str, text: str) -> Mapping[str, object]:
    imported = sysml_to_graph(text, project_id)
    repository = _services(request).repository(project_id)
    current = repository.load_graph(project_id)
    existing_ids = {item.id for item in current.entities}
    conflicts = sorted(existing_ids & {item.id for item in imported.entities})
    if conflicts:
        raise ContractViolation(f"SysML import conflicts with existing entity ids: {conflicts}")
    operations: list[object] = [AddEntity(item) for item in imported.entities]
    operations.extend(
        Relate(item.source_id, item.predicate, item.target_id, item.evidence_ids)
        for item in imported.relations
    )
    if not operations:
        raise ContractViolation("SysML import contains no model records")
    patch = Patch.create(
        project_id,
        "sysml.import",
        tuple(operations),
        "从 SysML v2 子集导入模型",
        current.revision,
    )
    revision = repository.append_patch(project_id, patch, current.revision)
    return {
        "status": "ok",
        "revision": revision.sequence,
        "entity_count": len(imported.entities),
        "relation_count": len(imported.relations),
    }


@resource_api.get("/model-profiles")
def list_model_profiles(request: Request):
    return {"status": "ok", **_services(request).settings.list_profiles()}


@resource_api.get("/model-profiles/presets")
def list_model_profile_presets(request: Request):
    return {"status": "ok", "presets": _services(request).settings.presets()}


@resource_api.post("/model-profiles")
async def save_model_profile(request: Request):
    try:
        return {"status": "ok", "profile": _services(request).settings.save_profile(await request.json())}
    except (ContractViolation, RflpError, OSError, ValueError) as exc:
        return _error(exc)


@resource_api.post("/model-profiles/test")
async def test_model_profile(request: Request):
    try:
        settings = _services(request).settings
        payload = _profile_test_payload(settings, await request.json())
        config = settings.profiles.config_for(payload)
        profile_id = str(config["id"])
        provider_id = str(config.get("provider") or "openai-compatible")
        model_id = str(config.get("model", ""))
        try:
            connection = _services(request).test_model_profile(config)
        except AdapterFailure as exc:
            connection = _connection_failure(exc)
        return {
            "status": "ok",
            "profile_id": profile_id,
            "provider_id": provider_id,
            "model_id": model_id,
            "connection": connection,
            **connection,
        }
    except (ContractViolation, RflpError, OSError, ValueError) as exc:
        return _error(exc)


@resource_api.delete("/model-profiles/{profile_id}")
def delete_model_profile(request: Request, profile_id: str):
    try:
        return {"status": "ok", **_services(request).settings.delete_profile(profile_id)}
    except (ContractViolation, RflpError, OSError, ValueError) as exc:
        return _error(exc)


@resource_api.post("/model-profiles/{profile_id}/activate")
def activate_model_profile(request: Request, profile_id: str):
    try:
        return {"status": "ok", "profile": _services(request).settings.activate_profile(profile_id)}
    except (ContractViolation, RflpError, OSError, ValueError) as exc:
        return _error(exc)
