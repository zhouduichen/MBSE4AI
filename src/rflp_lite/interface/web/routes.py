from __future__ import annotations

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Form, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from rflp_lite.application.run_catalog import registered_output
from rflp_lite.application.web_facade import WebFacade
from rflp_lite.domain.errors import ContractViolation, RflpError
from rflp_lite.interface.web.presenters import (
    CAPABILITIES,
    artifacts_context,
    baselines_context,
    candidates_context,
    evidence_context,
    page_context,
    rflp_context,
    run_detail_context,
    simulation_context,
    tasks_context,
)


router = APIRouter()
templates = Jinja2Templates(directory=Path(__file__).resolve().parent / "templates")


def _facade(request: Request) -> WebFacade:
    return request.app.state.facade


def _run_error(request: Request, message: object, status_code: int = 422) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="_run-error.html",
        context={"message": str(message)},
        status_code=status_code,
    )


@router.get("/", response_class=HTMLResponse)
def dashboard(request: Request) -> HTMLResponse:
    view = _facade(request).dashboard(None)
    latest = view["latest_run"]
    context = page_context(
        view["workspace"],
        workspaces=view["workspaces"],
        latest_run=latest,
        nav_result_hash=latest.result_hash if latest else None,
        counts=view["counts"],
        audit=view["audit"],
    )
    return templates.TemplateResponse(request=request, name="dashboard.html", context=context)


@router.post("/workspaces")
def create_workspace(request: Request, name: Annotated[str, Form()]) -> Response:
    workspace = _facade(request).create_workspace(name.strip())
    return RedirectResponse(url=f"/w/{workspace.name}", status_code=303)


@router.get("/w/{workspace_name}", response_class=HTMLResponse)
def workspace_dashboard(request: Request, workspace_name: str) -> HTMLResponse:
    view = _facade(request).dashboard(workspace_name)
    latest = view["latest_run"]
    context = page_context(
        view["workspace"],
        workspaces=view["workspaces"],
        latest_run=latest,
        nav_result_hash=latest.result_hash if latest else None,
        counts=view["counts"],
        audit=view["audit"],
    )
    return templates.TemplateResponse(request=request, name="dashboard.html", context=context)


@router.get("/w/{workspace_name}/runs", response_class=HTMLResponse)
def run_center(request: Request, workspace_name: str) -> HTMLResponse:
    facade = _facade(request)
    runs = facade.runs(workspace_name)
    context = page_context(
        facade.workspace(workspace_name),
        active="runs",
        nav_result_hash=runs[0].result_hash if runs else None,
        runs=runs,
    )
    return templates.TemplateResponse(request=request, name="run-center.html", context=context)


@router.post("/w/{workspace_name}/runs")
def start_run(
    request: Request,
    workspace_name: str,
    solver: Annotated[str, Form()],
    seed: Annotated[str, Form()],
) -> Response:
    try:
        parsed_seed = int(seed)
        if parsed_seed < 0:
            raise ValueError
    except ValueError:
        return _run_error(request, "Seed 必须是非负整数")
    try:
        record = _facade(request).execute(workspace_name, solver, parsed_seed)
    except (ContractViolation, RflpError, OSError) as exc:
        return _run_error(request, exc)
    location = f"/w/{workspace_name}/runs/{record.result_hash}"
    if request.headers.get("HX-Request") == "true":
        return Response(status_code=204, headers={"HX-Redirect": location})
    return RedirectResponse(location, status_code=303)


@router.get("/w/{workspace_name}/runs/{result_hash}", response_class=HTMLResponse)
def run_detail(request: Request, workspace_name: str, result_hash: str) -> HTMLResponse:
    facade = _facade(request)
    workspace = facade.workspace(workspace_name)
    record = facade.run(workspace_name, result_hash)
    return templates.TemplateResponse(
        request=request,
        name="run-detail.html",
        context=run_detail_context(workspace, record),
    )


def _run_page(request: Request, workspace_name: str, result_hash: str):
    facade = _facade(request)
    workspace = facade.workspace(workspace_name)
    return workspace, facade.run(workspace_name, result_hash)


@router.get("/w/{workspace_name}/runs/{result_hash}/model/artifacts")
def artifacts_page(request: Request, workspace_name: str, result_hash: str) -> Response:
    workspace, run = _run_page(request, workspace_name, result_hash)
    return templates.TemplateResponse(request=request, name="artifacts.html", context=artifacts_context(workspace, run))


@router.get("/w/{workspace_name}/runs/{result_hash}/model/rflp")
def rflp_page(request: Request, workspace_name: str, result_hash: str) -> Response:
    workspace, run = _run_page(request, workspace_name, result_hash)
    return templates.TemplateResponse(request=request, name="rflp-model.html", context=rflp_context(workspace, run))


@router.get("/w/{workspace_name}/runs/{result_hash}/decision/candidates")
def candidates_page(request: Request, workspace_name: str, result_hash: str) -> Response:
    workspace, run = _run_page(request, workspace_name, result_hash)
    return templates.TemplateResponse(request=request, name="candidates.html", context=candidates_context(workspace, run))


@router.get("/w/{workspace_name}/runs/{result_hash}/decision/simulation")
def simulation_page(request: Request, workspace_name: str, result_hash: str) -> Response:
    workspace, run = _run_page(request, workspace_name, result_hash)
    return templates.TemplateResponse(request=request, name="simulation.html", context=simulation_context(workspace, run))


@router.get("/w/{workspace_name}/runs/{result_hash}/governance/baselines")
def baselines_page(request: Request, workspace_name: str, result_hash: str) -> Response:
    workspace, run = _run_page(request, workspace_name, result_hash)
    return templates.TemplateResponse(request=request, name="baselines.html", context=baselines_context(workspace, run))


@router.get("/w/{workspace_name}/runs/{result_hash}/governance/tasks")
def tasks_page(request: Request, workspace_name: str, result_hash: str) -> Response:
    workspace, run = _run_page(request, workspace_name, result_hash)
    return templates.TemplateResponse(request=request, name="tasks.html", context=tasks_context(workspace, run))


@router.get("/w/{workspace_name}/runs/{result_hash}/governance/evidence")
def evidence_page(request: Request, workspace_name: str, result_hash: str) -> Response:
    workspace, run = _run_page(request, workspace_name, result_hash)
    audit = _facade(request).audit(workspace_name)
    return templates.TemplateResponse(request=request, name="evidence.html", context=evidence_context(workspace, run, audit))


@router.get("/w/{workspace_name}/runs/{result_hash}/downloads/{filename}")
def download_output(request: Request, workspace_name: str, result_hash: str, filename: str) -> Response:
    _, run = _run_page(request, workspace_name, result_hash)
    try:
        path = registered_output(run, filename)
    except ContractViolation as exc:
        return HTMLResponse(str(exc), status_code=404)
    return FileResponse(path, media_type="application/json", filename=filename)


@router.get("/capabilities", response_class=HTMLResponse)
def capabilities(request: Request) -> HTMLResponse:
    workspaces = _facade(request).workspaces()
    workspace = workspaces[0] if workspaces else None
    context = page_context(workspace, workspaces=workspaces, active="capabilities", capabilities=CAPABILITIES)
    return templates.TemplateResponse(request=request, name="capabilities.html", context=context)
