"""Resource-oriented API for the AI4MBSE Harness."""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Mapping

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

from rflp_lite.domain.entities import EntityKind
from rflp_lite.domain.errors import ConcurrentModificationError, ContractViolation, RflpError
from rflp_lite.domain.model import Patch, UpdateEntity
from rflp_lite.methodology.contracts import Phase
from rflp_lite.retrieval.planner import KnowledgeGap


resource_api = APIRouter(tags=["AI4MBSE Harness"])


def _services(request: Request):
    services = getattr(request.app.state, "container", None)
    if services is None or services.v2 is None:
        raise RuntimeError("v2 services are not configured")
    return services.v2


def _run_payload(summary) -> dict[str, object]:
    return {
        "run_id": summary.run_id,
        "project_id": summary.project_id,
        "phase": summary.phase.value,
        "status": summary.status.value,
        "completed_tasks": list(summary.completed_tasks),
        "diagnostics": list(summary.diagnostics),
    }


def _error(exc: Exception) -> JSONResponse:
    status = 409 if isinstance(exc, ConcurrentModificationError) else 422
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
        phase = Phase(str(payload.get("phase", Phase.OPERATIONAL.value))) if isinstance(payload, Mapping) else Phase.OPERATIONAL
        return {"status": "ok", "run": _run_payload(_services(request).analysis(project_id).run(project_id, phase))}
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
        result = _services(request).analysis(project_id).repair(project_id, str(payload["issue_id"]))
        return {"status": "ok", "run": _run_payload(result)}
    except (ContractViolation, RflpError, OSError, ValueError) as exc:
        return _error(exc)


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


@resource_api.post("/model-profiles/{profile_id}/activate")
def activate_model_profile(request: Request, profile_id: str):
    try:
        return {"status": "ok", "profile": _services(request).settings.activate_profile(profile_id)}
    except (ContractViolation, RflpError, OSError, ValueError) as exc:
        return _error(exc)
