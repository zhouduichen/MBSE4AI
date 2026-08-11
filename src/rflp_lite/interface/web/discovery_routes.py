"""Thin HTML routes for intelligent MBSE discovery."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates


discovery_router = APIRouter()
templates = Jinja2Templates(directory=Path(__file__).resolve().parent / "templates")


@discovery_router.get("/w/{workspace_name}/requirements/discovery", response_class=HTMLResponse)
def page(request: Request, workspace_name: str):
    facade = request.app.state.facade
    return templates.TemplateResponse(request=request, name="requirements-discovery.html", context={"workspace": facade.workspace(workspace_name), "workspaces": facade.workspaces(), "active": "requirements-discovery", "state": facade.requirements(workspace_name), "pack_id": "urban-medical-aam-v1"})


@discovery_router.get("/w/{workspace_name}/requirements/discovery/diagram.svg")
def diagram(request: Request, workspace_name: str, type: str = "environment"):
    rendered = request.app.state.facade.render_discovery_diagram(workspace_name, "urban-medical-aam-v1", type)
    return Response(content=rendered[0].content, media_type="image/svg+xml")


@discovery_router.post("/w/{workspace_name}/requirements/discovery/draft")
async def draft(request: Request, workspace_name: str):
    form = await request.form()
    request.app.state.facade.draft_discovery(workspace_name, str(form.get("pack_id", "urban-medical-aam-v1")))
    return RedirectResponse(f"/w/{workspace_name}/requirements/discovery", status_code=303)
