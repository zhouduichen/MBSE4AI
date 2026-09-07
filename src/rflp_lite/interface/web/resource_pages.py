"""Five small resource pages backed by the v2 application services."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.templating import Jinja2Templates


resource_pages = APIRouter()
templates = Jinja2Templates(directory=Path(__file__).resolve().parent / "templates")


def _v2(request: Request):
    return request.app.state.container.v2


@resource_pages.get("/ui/projects", name="projects_page")
def projects_page(request: Request):
    return templates.TemplateResponse(request=request, name="projects.html", context={"projects": _v2(request).projects.list()})


@resource_pages.get("/ui/projects/{project_id}/analysis", name="analysis_page")
def analysis_page(request: Request, project_id: str):
    return templates.TemplateResponse(request=request, name="analysis.html", context={"project": _v2(request).projects.summary(project_id), "project_id": project_id})


@resource_pages.get("/ui/projects/{project_id}/model", name="model_page")
def model_page(request: Request, project_id: str):
    return templates.TemplateResponse(request=request, name="model.html", context={"project": _v2(request).projects.summary(project_id), "project_id": project_id})


@resource_pages.get("/ui/projects/{project_id}/evidence", name="evidence_page")
def evidence_page(request: Request, project_id: str):
    services = _v2(request)
    return templates.TemplateResponse(request=request, name="evidence-issues.html", context={"project": services.projects.summary(project_id), "evidence": services.evidence(project_id).list(project_id), "issues": services.model(project_id).issues(project_id), "project_id": project_id})


@resource_pages.get("/ui/settings", name="settings_page")
def settings_page(request: Request):
    return templates.TemplateResponse(request=request, name="settings.html", context={"settings": _v2(request).settings.list_profiles()})
