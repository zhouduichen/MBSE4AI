"""Resource-oriented API for the AI4MBSE Harness."""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Mapping
from urllib.error import HTTPError, URLError
from urllib.request import Request as URLRequest
from urllib.request import urlopen
from uuid import uuid4

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

from rflp_lite.domain.entities import EntityKind
from rflp_lite.domain.errors import ConcurrentModificationError, ContractViolation, NotFoundError, RflpError
from rflp_lite.domain.model import Patch, UpdateEntity
from rflp_lite.methodology.contracts import Phase
from rflp_lite.methodology.gates import global_gate
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


def _services(request: Request):
    services = getattr(request.app.state, "container", None)
    if services is None or services.v2 is None:
        raise RuntimeError("v2 services are not configured")
    return services.v2


def _run_payload(summary) -> dict[str, object]:
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
    for key in ("phase_results", "gate_results", "closure", "current_task", "repair", "runtime"):
        if key in data:
            payload[key] = data[key]
    return payload


def _attach_runtime_metadata(run: dict[str, object], analysis) -> dict[str, object]:
    runner = getattr(analysis, "runner", None)
    selection = getattr(runner, "runtime_selection", None)
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


def _pipeline_fallback(analysis, project_id: str, *, requested_run_id: str | None, force_run: bool) -> dict[str, object]:
    pipeline_id = requested_run_id or f"pipeline-{uuid4().hex[:16]}"
    phase_results: list[dict[str, object]] = []
    gate_results: list[dict[str, object]] = []
    diagnostics: list[str] = []
    all_passed = True
    for phase in (Phase.OPERATIONAL, Phase.FUNCTIONAL, Phase.LOGICAL_PHYSICAL, Phase.ASSURANCE):
        phase_run_id = f"{pipeline_id}-{phase.value}" if force_run else None
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
    closure: dict[str, object]
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


def _orchestrator_payload(analysis, project_id: str, result, *, force_run: bool) -> dict[str, object]:
    payload = _run_payload(result)
    phase_order = [phase.value for phase, _label in ((Phase.OPERATIONAL, ""), (Phase.FUNCTIONAL, ""), (Phase.LOGICAL_PHYSICAL, ""), (Phase.ASSURANCE, ""), (Phase.CLOSURE, ""))]
    result_phase = str(payload.get("phase", Phase.OPERATIONAL.value))
    result_status = str(payload.get("status", "degraded"))
    try:
        result_index = phase_order.index(result_phase)
    except ValueError:
        result_index = 0
    phase_results = [
        {
            "phase": phase,
            "status": "completed" if index < result_index and result_status == "completed" else result_status if index == result_index else "pending",
            "completed_tasks": list(payload.get("completed_tasks", ())) if index == result_index else [],
            "diagnostics": list(payload.get("diagnostics", ())) if index == result_index else [],
        }
        for index, phase in enumerate(phase_order)
    ]
    gate_results: list[dict[str, object]] = []
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


def _invoke_pipeline(analysis, project_id: str, *, run_id: str | None, force_run: bool) -> dict[str, object]:
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


def _profile_test_payload(settings, raw: object) -> dict[str, object]:
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


def _probe_model_profile(config: Mapping[str, object]) -> dict[str, object]:
    base_url = str(config.get("base_url", "")).rstrip("/")
    headers = {"accept": "application/json"}
    api_key = str(config.get("api_key", "")).strip()
    if api_key:
        headers["authorization"] = f"Bearer {api_key}"
    request = URLRequest(f"{base_url}/models", headers=headers, method="GET")
    try:
        with urlopen(request, timeout=min(5, int(config.get("timeout_seconds", 5)))) as response:
            return {"connected": 200 <= response.status < 300, "connection_status": "connected", "status_code": response.status, "message": "Model endpoint responded."}
    except HTTPError as exc:
        return {"connected": False, "connection_status": "rejected", "status_code": exc.code, "message": "Model endpoint rejected the connection test."}
    except (URLError, TimeoutError, OSError) as exc:
        return {"connected": False, "connection_status": "unreachable", "status_code": None, "message": str(exc.reason if isinstance(exc, URLError) else exc)}


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
    status = 404 if isinstance(exc, NotFoundError) else 409 if isinstance(exc, ConcurrentModificationError) else 422
    return JSONResponse({"status": "failed", "error": type(exc).__name__, "message": str(exc)}, status_code=status)


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


@resource_api.post("/projects/{project_id}/documents")
async def ingest_document(request: Request, project_id: str):
    try:
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
        mode = str(payload.get("mode", "pipeline" if "phase" not in payload else "phase")).casefold()
        force_run = bool(payload.get("force_run", False))
        requested_run_id = str(payload.get("run_id", "")).strip() or None
        if force_run and requested_run_id is None:
            requested_run_id = f"web-run-{uuid4().hex[:16]}"
        analysis = _analysis_service(request, project_id)
        if mode == "pipeline":
            run = _invoke_pipeline(analysis, project_id, run_id=requested_run_id, force_run=force_run)
        else:
            phase = Phase(str(payload.get("phase", Phase.OPERATIONAL.value)))
            run = _run_payload(_call_run(analysis, project_id, phase, requested_run_id, force_run=force_run))
            run["mode"] = "phase"
            run["force_run"] = force_run
        _attach_runtime_metadata(run, analysis)
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


@resource_api.post("/projects/{project_id}/evidence/search")
async def search_evidence(request: Request, project_id: str):
    try:
        payload = await request.json()
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
        content, media_type = _services(request).render(project_id).export(project_id, view_id, output_format)
        return Response(content=content, media_type=media_type)
    except (ContractViolation, RflpError, OSError, ValueError) as exc:
        return _error(exc)


@resource_api.get("/model-profiles")
def list_model_profiles(request: Request):
    return {"status": "ok", **_services(request).settings.list_profiles()}


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
        provider_id = str(config.get("provider_id") or "openai-compatible")
        model_id = str(config.get("model", ""))
        if str(config.get("kind", "remote")) == "remote" and not str(config.get("api_key", "")).strip():
            connection = {
                "connected": False,
                "connection_status": "not_configured",
                "status_code": None,
                "message": "Remote profile has no API key configured.",
            }
        else:
            connection = _probe_model_profile(config)
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


@resource_api.post("/model-profiles/{profile_id}/activate")
def activate_model_profile(request: Request, profile_id: str):
    try:
        return {"status": "ok", "profile": _services(request).settings.activate_profile(profile_id)}
    except (ContractViolation, RflpError, OSError, ValueError) as exc:
        return _error(exc)
