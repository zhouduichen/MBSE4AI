"""Thin HTML routes for intelligent MBSE discovery."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from rflp_lite.application.diagrams.specifications import DIAGRAM_TYPES
from rflp_lite.domain.errors import ContractViolation, RflpError


discovery_router = APIRouter()
templates = Jinja2Templates(directory=Path(__file__).resolve().parent / "templates")

DEFAULT_PACK = "urban-medical-aam-v1"


def _run_error(request: Request, exc: Exception) -> HTMLResponse:
    context: dict[str, object] = {"message": str(exc)}
    if request.headers.get("HX-Request") != "true":
        context = {
            "message": str(exc),
            "status_code": 422,
            "workspace": None,
        }
        name = "error.html"
    else:
        name = "_run-error.html"
    return templates.TemplateResponse(
        request=request,
        name=name,
        context=context,
        status_code=422,
    )


def _discovery_context(request: Request, workspace_name: str) -> dict[str, object]:
    facade = request.app.state.facade
    state = facade.requirements(workspace_name)
    discovery = state.get("discovery", {}) if isinstance(state, dict) else {}
    graph = discovery.get("accepted_graph", {}) if isinstance(discovery, Mapping) else {}
    groups = discovery.get("candidate_sets", []) if isinstance(discovery, Mapping) else []
    items = [
        item
        for group in groups
        if isinstance(group, Mapping)
        for item in group.get("items", ())
        if isinstance(item, Mapping)
    ]
    return {
        "workspace": facade.workspace(workspace_name),
        "workspaces": facade.workspaces(),
        "active": "requirements-discovery",
        "state": state,
        "pack_id": DEFAULT_PACK,
        "diagram_types": DIAGRAM_TYPES,
        "has_accepted_graph": bool(graph and graph.get("elements")),
        "candidate_count": len(items),
        "accepted_count": sum(1 for item in items if item.get("status") == "accepted"),
    }


@discovery_router.get("/w/{workspace_name}/requirements/discovery", response_class=HTMLResponse)
def page(request: Request, workspace_name: str):
    return templates.TemplateResponse(
        request=request,
        name="requirements-discovery.html",
        context=_discovery_context(request, workspace_name),
    )


@discovery_router.post("/w/{workspace_name}/requirements/discovery/draft")
async def draft(request: Request, workspace_name: str):
    try:
        form = await request.form()
        request.app.state.facade.draft_discovery(
            workspace_name, str(form.get("pack_id", DEFAULT_PACK))
        )
    except (ContractViolation, RflpError, OSError, ValueError) as exc:
        return _run_error(request, exc)
    return RedirectResponse(f"/w/{workspace_name}/requirements/discovery", status_code=303)


@discovery_router.post("/w/{workspace_name}/requirements/discovery/review")
async def review(request: Request, workspace_name: str):
    try:
        form = await request.form()
        request.app.state.facade.review_discovery(
            workspace_name,
            str(form.get("candidate_id", "")),
            str(form.get("decision", "")),
            int(form.get("expected_revision", -1)),
            str(form.get("pack_id", DEFAULT_PACK)),
        )
    except (ContractViolation, RflpError, OSError, ValueError) as exc:
        return _run_error(request, exc)
    return RedirectResponse(f"/w/{workspace_name}/requirements/discovery", status_code=303)


@discovery_router.post("/w/{workspace_name}/requirements/discovery/edit")
async def edit(request: Request, workspace_name: str):
    try:
        form = await request.form()
        raw_payload = str(form.get("payload", ""))
        try:
            payload = json.loads(raw_payload)
        except json.JSONDecodeError as exc:
            raise ContractViolation("编辑候选需要有效的 payload JSON") from exc
        if not isinstance(payload, dict):
            raise ContractViolation("候选 payload 必须是对象")
        payload["name"] = str(form.get("name", "")).strip()
        request.app.state.facade.edit_discovery(
            workspace_name,
            str(form.get("candidate_id", "")),
            payload,
            int(form.get("expected_revision", -1)),
            str(form.get("pack_id", DEFAULT_PACK)),
        )
    except (ContractViolation, RflpError, OSError, ValueError) as exc:
        return _run_error(request, exc)
    return RedirectResponse(f"/w/{workspace_name}/requirements/discovery", status_code=303)


@discovery_router.post("/w/{workspace_name}/requirements/discovery/finalize")
async def finalize(request: Request, workspace_name: str):
    try:
        form = await request.form()
        request.app.state.facade.finalize_discovery(
            workspace_name, str(form.get("pack_id", DEFAULT_PACK))
        )
    except (ContractViolation, RflpError, OSError, ValueError) as exc:
        return _run_error(request, exc)
    return RedirectResponse(f"/w/{workspace_name}/requirements/discovery", status_code=303)


@discovery_router.get("/w/{workspace_name}/requirements/discovery/diagram.svg")
def diagram(request: Request, workspace_name: str, type: str = "environment"):
    try:
        rendered = request.app.state.facade.render_discovery_diagram(
            workspace_name, DEFAULT_PACK, type
        )
    except (ContractViolation, RflpError, OSError, ValueError) as exc:
        return _run_error(request, exc)
    return Response(content=rendered[0].content, media_type="image/svg+xml")