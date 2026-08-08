from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from rflp_lite.application.run_catalog import registered_output
from rflp_lite.adapters.test_execution_config import build_limits
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


def _requirements_location(workspace_name: str) -> str:
    return f"/w/{workspace_name}/requirements"


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


@router.get("/w/{workspace_name}/requirements", response_class=HTMLResponse)
def requirements_page(request: Request, workspace_name: str) -> HTMLResponse:
    facade = _facade(request)
    workspace = facade.workspace(workspace_name)
    runs = facade.runs(workspace_name)
    context = page_context(
        workspace,
        active="requirements",
        nav_result_hash=runs[0].result_hash if runs else None,
        state=facade.requirements(workspace_name),
    )
    return templates.TemplateResponse(
        request=request, name="requirements-workbench.html", context=context
    )


@router.get("/w/{workspace_name}/profile.json")
def profile_json(request: Request, workspace_name: str) -> Response:
    return Response(
        content=json.dumps(
            _facade(request).profile(workspace_name), ensure_ascii=False, sort_keys=True
        )
        + "\n",
        media_type="application/json",
    )


@router.post("/w/{workspace_name}/profile.json")
async def save_profile_json(request: Request, workspace_name: str) -> Response:
    try:
        payload = await request.json()
        profile = _facade(request).save_profile(workspace_name, payload)
    except (ContractViolation, RflpError, OSError, ValueError) as exc:
        return Response(
            content=json.dumps(
                {"status": "failed", "error": str(exc)}, ensure_ascii=False
            )
            + "\n",
            status_code=422,
            media_type="application/json",
        )
    return Response(
        content=json.dumps({"status": "ok", "profile": profile}, ensure_ascii=False) + "\n",
        media_type="application/json",
    )


@router.post("/w/{workspace_name}/requirements/analyze")
async def analyze_requirements(
    request: Request,
    workspace_name: str,
    text: Annotated[str, Form()] = "",
    artifact: UploadFile | None = File(default=None),
    merge: Annotated[str, Form()] = "",
) -> Response:
    try:
        if artifact is not None and artifact.filename:
            filename, content = artifact.filename, await artifact.read()
        else:
            filename, content = "requirements.txt", text.encode("utf-8")
        _facade(request).analyze_requirements(
            workspace_name, filename, content, merge=bool(merge)
        )
    except (ContractViolation, RflpError, OSError) as exc:
        return _run_error(request, exc)
    return RedirectResponse(_requirements_location(workspace_name), status_code=303)


@router.post("/w/{workspace_name}/requirements/scenarios")
def create_requirement_scenario(
    request: Request,
    workspace_name: str,
    title: Annotated[str, Form()],
    description: Annotated[str, Form()],
    steps: Annotated[str, Form()],
    expected_outcomes: Annotated[str, Form()],
    actors: Annotated[str, Form()] = "",
    preconditions: Annotated[str, Form()] = "",
    faults: Annotated[str, Form()] = "",
    requirement_ids: Annotated[str, Form()] = "",
) -> Response:
    try:
        _facade(request).add_requirement_scenario(
            workspace_name,
            title=title,
            description=description,
            actors=actors,
            preconditions=preconditions,
            steps=steps,
            expected_outcomes=expected_outcomes,
            faults=faults,
            requirement_ids=requirement_ids,
        )
    except (ContractViolation, RflpError, OSError) as exc:
        return _run_error(request, exc)
    return RedirectResponse(_requirements_location(workspace_name), status_code=303)


@router.post("/w/{workspace_name}/requirements/scenarios/delete")
def delete_requirement_scenario(
    request: Request,
    workspace_name: str,
    scenario_id: Annotated[str, Form()],
) -> Response:
    try:
        _facade(request).delete_requirement_scenario(workspace_name, scenario_id)
    except (ContractViolation, RflpError, OSError) as exc:
        return _run_error(request, exc)
    return RedirectResponse(_requirements_location(workspace_name), status_code=303)


@router.post("/w/{workspace_name}/requirements/scenarios/execute")
def execute_requirement_scenario(
    request: Request,
    workspace_name: str,
    scenario_id: Annotated[str, Form()],
) -> Response:
    try:
        _facade(request).execute_requirement_scenario(workspace_name, scenario_id)
    except (ContractViolation, RflpError, OSError) as exc:
        return _run_error(request, exc)
    return RedirectResponse(_requirements_location(workspace_name), status_code=303)


@router.post("/w/{workspace_name}/requirements/review")
def review_requirement(
    request: Request,
    workspace_name: str,
    group: Annotated[str, Form()],
    item_id: Annotated[str, Form()],
    status: Annotated[str, Form()],
    value: Annotated[str, Form()] = "",
) -> Response:
    try:
        _facade(request).review_requirement_item(
            workspace_name, group, item_id, status, value
        )
    except (ContractViolation, RflpError, OSError) as exc:
        return _run_error(request, exc)
    return RedirectResponse(_requirements_location(workspace_name), status_code=303)


@router.post("/w/{workspace_name}/requirements/accept-traceable")
def accept_traceable_requirements(request: Request, workspace_name: str) -> Response:
    try:
        _facade(request).accept_traceable_requirements(workspace_name)
    except (ContractViolation, RflpError, OSError) as exc:
        return _run_error(request, exc)
    return RedirectResponse(_requirements_location(workspace_name), status_code=303)


@router.post("/w/{workspace_name}/requirements/generate")
def generate_requirements(request: Request, workspace_name: str) -> Response:
    try:
        _facade(request).generate_requirements_model(workspace_name)
    except (ContractViolation, RflpError, OSError) as exc:
        return _run_error(request, exc)
    return RedirectResponse(_requirements_location(workspace_name), status_code=303)


@router.post("/w/{workspace_name}/requirements/ai")
def analyze_requirements_with_ai(request: Request, workspace_name: str) -> Response:
    try:
        _facade(request).analyze_requirements_with_ai(workspace_name)
    except (ContractViolation, RflpError, OSError) as exc:
        return _run_error(request, exc)
    return RedirectResponse(_requirements_location(workspace_name), status_code=303)


@router.get("/w/{workspace_name}/requirements/model.json")
def requirements_json(request: Request, workspace_name: str) -> Response:
    state = _facade(request).requirements(workspace_name)
    if not state or not state.get("rflp"):
        return HTMLResponse("RFLP model not generated", status_code=404)
    content = __import__("json").dumps(
        state["rflp"], ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return Response(
        content=content + "\n",
        media_type="application/json",
        headers={"Content-Disposition": 'attachment; filename="rflp-model.json"'},
    )


@router.get("/w/{workspace_name}/requirements/sysml-lite.json")
def requirements_sysml_lite_json(request: Request, workspace_name: str) -> Response:
    try:
        payload = _facade(request).export_requirements_rflp(workspace_name)
    except (ContractViolation, RflpError) as exc:
        return HTMLResponse(str(exc), status_code=404)
    return Response(
        content=json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n",
        media_type="application/json",
        headers={"Content-Disposition": 'attachment; filename="rflp-sysml-lite.json"'},
    )


@router.post("/w/{workspace_name}/requirements/sysml-lite.json")
async def import_requirements_sysml_lite_json(request: Request, workspace_name: str) -> Response:
    try:
        payload = await request.json()
        state = _facade(request).import_requirements_rflp(workspace_name, payload)
    except (ContractViolation, RflpError, ValueError) as exc:
        return Response(
            content=json.dumps({"status": "failed", "error": str(exc)}, ensure_ascii=False) + "\n",
            status_code=422,
            media_type="application/json",
        )
    return Response(
        content=json.dumps({"status": "ok", "model": state["rflp"]}, ensure_ascii=False) + "\n",
        media_type="application/json",
    )


@router.get("/w/{workspace_name}/requirements/scenarios.json")
def requirements_scenarios_json(request: Request, workspace_name: str) -> Response:
    state = _facade(request).requirements(workspace_name)
    if not state:
        return HTMLResponse("requirements workbench not found", status_code=404)
    content = json.dumps(
        state.get("scenarios", ()), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return Response(
        content=content + "\n",
        media_type="application/json",
        headers={"Content-Disposition": 'attachment; filename="scenarios.json"'},
    )


@router.get("/w/{workspace_name}/requirements/scenario-runs.json")
def requirements_scenario_runs_json(request: Request, workspace_name: str) -> Response:
    state = _facade(request).requirements(workspace_name)
    if not state:
        return HTMLResponse("requirements workbench not found", status_code=404)
    content = json.dumps(
        state.get("scenario_runs", ()), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return Response(
        content=content + "\n",
        media_type="application/json",
        headers={"Content-Disposition": 'attachment; filename="scenario-runs.json"'},
    )


@router.get("/w/{workspace_name}/jobs/{job_id}.json")
def job_json(request: Request, workspace_name: str, job_id: str) -> Response:
    job = _facade(request).job(workspace_name, job_id)
    if job is None:
        return HTMLResponse("job not found", status_code=404)
    return Response(
        content=json.dumps(job, ensure_ascii=False, sort_keys=True) + "\n",
        media_type="application/json",
    )
@router.get("/w/{workspace_name}/requirements/model.svg")
def requirements_svg(request: Request, workspace_name: str) -> Response:
    state = _facade(request).requirements(workspace_name)
    if not state or not state.get("svg"):
        return HTMLResponse("RFLP SVG not generated", status_code=404)
    return Response(
        content=state["svg"],
        media_type="image/svg+xml",
        headers={"Content-Disposition": 'attachment; filename="rflp-model.svg"'},
    )


@router.get("/w/{workspace_name}/requirements/model.sysml")
def requirements_sysml_v2(request: Request, workspace_name: str) -> Response:
    try:
        content = _facade(request).export_requirements_sysml_v2(workspace_name)
    except (ContractViolation, RflpError) as exc:
        return HTMLResponse(str(exc), status_code=404)
    return Response(
        content=content,
        media_type="text/plain",
        headers={"Content-Disposition": 'attachment; filename="rflp-model.sysml"'},
    )


@router.post("/w/{workspace_name}/requirements/model.sysml")
async def import_requirements_sysml_v2(request: Request, workspace_name: str) -> Response:
    try:
        text = (await request.body()).decode("utf-8")
        state = _facade(request).import_requirements_sysml_v2(workspace_name, text)
    except (ContractViolation, RflpError, OSError, UnicodeDecodeError) as exc:
        return Response(
            content=json.dumps({"status": "failed", "error": str(exc)}, ensure_ascii=False) + "\n",
            status_code=422,
            media_type="application/json",
        )
    return Response(
        content=json.dumps({"status": "ok", "rflp": state["rflp"]}, ensure_ascii=False) + "\n",
        media_type="application/json",
    )


_PROJECT_DOWNLOADS = {
    "baseline.json": lambda state: state.get("baseline"),
    "actual-model.json": lambda state: (state.get("project") or {}).get("actual"),
    "matches.json": lambda state: (state.get("project") or {}).get("matches"),
    "delta.json": lambda state: (state.get("project") or {}).get("delta"),
    "task-contracts.json": lambda state: (state.get("project") or {}).get("tasks"),
    "evidence.json": lambda state: (state.get("project") or {}).get("evidence"),
    "project.json": lambda state: state.get("project"),
}


@router.get("/w/{workspace_name}/project", response_class=HTMLResponse)
def project_page(request: Request, workspace_name: str) -> HTMLResponse:
    facade = _facade(request)
    workspace = facade.workspace(workspace_name)
    runs = facade.runs(workspace_name)
    context = page_context(
        workspace,
        active="project",
        nav_result_hash=runs[0].result_hash if runs else None,
        state=facade.requirements(workspace_name),
    )
    return templates.TemplateResponse(
        request=request, name="project-bridge.html", context=context
    )


@router.post("/w/{workspace_name}/project/approve-baseline")
def approve_baseline(request: Request, workspace_name: str) -> Response:
    try:
        _facade(request).approve_requirements_baseline(workspace_name)
    except (ContractViolation, RflpError, OSError) as exc:
        return _run_error(request, exc)
    return RedirectResponse(f"/w/{workspace_name}/project", status_code=303)


@router.post("/w/{workspace_name}/project/analyze")
def analyze_project(
    request: Request,
    workspace_name: str,
    source: Annotated[str, Form()],
) -> Response:
    try:
        _facade(request).analyze_workspace_project(workspace_name, source.strip())
    except (ContractViolation, RflpError, OSError) as exc:
        return _run_error(request, exc)
    return RedirectResponse(f"/w/{workspace_name}/project", status_code=303)


@router.post("/w/{workspace_name}/project/verify")
def verify_project(
    request: Request,
    workspace_name: str,
    source: Annotated[str, Form()],
) -> Response:
    try:
        _facade(request).verify_workspace_project(workspace_name, source.strip())
    except (ContractViolation, RflpError, OSError) as exc:
        return _run_error(request, exc)
    return RedirectResponse(f"/w/{workspace_name}/project", status_code=303)


@router.post("/w/{workspace_name}/project/test")
def test_project(
    request: Request,
    workspace_name: str,
    runner: Annotated[list[str] | None, Form()] = None,
    timeout: Annotated[int, Form()] = 60,
    memory_mib: Annotated[int, Form()] = 1024,
    max_open_files: Annotated[int, Form()] = 1024,
    output_mib: Annotated[int, Form()] = 5,
    jobs: Annotated[int, Form()] = 1,
    no_cache: Annotated[str | None, Form()] = None,
) -> Response:
    try:
        limits = build_limits(
            timeout_seconds=timeout,
            memory_mib=memory_mib,
            max_open_files=max_open_files,
            output_mib=output_mib,
        )
        _facade(request).test_workspace_project(
            workspace_name,
            runners=tuple(runner or ("pytest",)),
            limits=limits,
            jobs=jobs,
            use_cache=no_cache is None,
        )
    except (ContractViolation, RflpError, OSError) as exc:
        return _run_error(request, exc)
    return RedirectResponse(f"/w/{workspace_name}/project", status_code=303)


@router.get("/w/{workspace_name}/project/download/{filename}")
def project_download(
    request: Request, workspace_name: str, filename: str
) -> Response:
    state = _facade(request).requirements(workspace_name)
    if not state or filename not in _PROJECT_DOWNLOADS:
        return HTMLResponse("project output not available", status_code=404)
    content = _PROJECT_DOWNLOADS[filename](state)
    if content is None:
        return HTMLResponse("project output not available", status_code=404)
    return Response(
        content=json.dumps(content, ensure_ascii=False, sort_keys=True) + "\n",
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


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


@router.get("/w/{workspace_name}/runs/{result_hash}/export.json")
def export_run_json(request: Request, workspace_name: str, result_hash: str) -> Response:
    return Response(
        content=json.dumps(
            _facade(request).export_run(workspace_name, result_hash),
            ensure_ascii=False,
            sort_keys=True,
        )
        + "\n",
        media_type="application/json",
        headers={"Content-Disposition": 'attachment; filename="run-export.json"'},
    )


@router.post("/w/{workspace_name}/runs/{result_hash}/mlflow")
async def track_run_mlflow(request: Request, workspace_name: str, result_hash: str) -> Response:
    try:
        raw = await request.body()
        payload = json.loads(raw.decode("utf-8")) if raw else {}
        if not isinstance(payload, dict):
            raise ContractViolation("MLflow payload must be an object")
        result = _facade(request).track_run_with_mlflow(
            workspace_name,
            result_hash,
            tracking_uri=payload.get("tracking_uri"),
            experiment_name=str(payload.get("experiment_name", "rflp-lite")),
        )
    except (ContractViolation, RflpError, OSError, ValueError) as exc:
        return Response(
            content=json.dumps({"status": "failed", "error": str(exc)}, ensure_ascii=False) + "\n",
            status_code=422,
            media_type="application/json",
        )
    return Response(
        content=json.dumps(result, ensure_ascii=False, sort_keys=True) + "\n",
        media_type="application/json",
    )


@router.get("/capabilities", response_class=HTMLResponse)
def capabilities(request: Request) -> HTMLResponse:
    workspaces = _facade(request).workspaces()
    workspace = workspaces[0] if workspaces else None
    context = page_context(workspace, workspaces=workspaces, active="capabilities", capabilities=CAPABILITIES)
    return templates.TemplateResponse(request=request, name="capabilities.html", context=context)
