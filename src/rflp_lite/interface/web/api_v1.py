from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

from rflp_lite.domain.errors import ContractViolation, RflpError


api_v1 = APIRouter(prefix="/api/v1", tags=["local-mvp"])


def _error(exc: Exception, status_code: int = 422) -> JSONResponse:
    return JSONResponse(
        {"status": "failed", "error": type(exc).__name__, "message": str(exc)},
        status_code=status_code,
    )


def _facade(request: Request):
    return request.app.state.facade


@api_v1.get("/llm/profiles", response_model=None)
def llm_profiles(request: Request) -> dict[str, object]:
    return {"status": "ok", **_facade(request).llm_snapshot()}


@api_v1.get("/llm/presets", response_model=None)
def llm_presets(request: Request) -> dict[str, object]:
    return {"status": "ok", "presets": _facade(request).llm_presets()}


@api_v1.post("/llm/profiles", response_model=None)
async def save_llm_profile(request: Request) -> JSONResponse | dict[str, object]:
    try:
        payload = await request.json()
        return {"status": "ok", "profile": _facade(request).save_llm_profile(payload)}
    except (ContractViolation, RflpError, OSError, ValueError) as exc:
        return _error(exc)


@api_v1.post("/llm/test", response_model=None)
async def test_llm_profile(request: Request) -> JSONResponse | dict[str, object]:
    try:
        payload = await request.json()
        return _facade(request).test_llm_profile(payload)
    except (ContractViolation, RflpError, OSError, ValueError) as exc:
        return _error(exc)


@api_v1.post("/llm/profiles/{profile_id}/activate", response_model=None)
def activate_llm_profile(request: Request, profile_id: str) -> JSONResponse | dict[str, object]:
    try:
        return {"status": "ok", "profile": _facade(request).activate_llm_profile(profile_id)}
    except (ContractViolation, RflpError, OSError, ValueError) as exc:
        return _error(exc)


@api_v1.delete("/llm/profiles/{profile_id}", response_model=None)
def delete_llm_profile(request: Request, profile_id: str) -> JSONResponse | dict[str, object]:
    try:
        _facade(request).delete_llm_profile(profile_id)
        return {"status": "ok"}
    except (ContractViolation, RflpError, OSError, ValueError) as exc:
        return _error(exc)


@api_v1.get("/workspaces")
def workspaces(request: Request) -> dict[str, object]:
    return {"status": "ok", "workspaces": [item.name for item in _facade(request).workspaces()]}


@api_v1.get("/plugins")
def plugins(request: Request) -> dict[str, object]:
    return {"status": "ok", "plugins": _facade(request).plugins()}


@api_v1.post("/plugins/{name}", response_model=None)
async def invoke_plugin(request: Request, name: str) -> JSONResponse | dict[str, object]:
    try:
        payload = await request.json()
        if not isinstance(payload, dict):
            raise ContractViolation("plugin payload must be an object")
        return _facade(request).invoke_plugin(name, payload)
    except (ContractViolation, RflpError, OSError, ValueError) as exc:
        return _error(exc)


@api_v1.get("/workspaces/{workspace_name}/requirements", response_model=None)
def requirements(request: Request, workspace_name: str) -> JSONResponse | dict[str, object]:
    try:
        state = _facade(request).requirements(workspace_name)
        if state is None:
            return _error(ContractViolation("requirements workbench is empty"), 404)
        return {"status": "ok", "requirements": state}
    except (ContractViolation, RflpError, OSError) as exc:
        return _error(exc, 404)


@api_v1.post("/workspaces/{workspace_name}/scenarios", response_model=None)
async def create_scenario(request: Request, workspace_name: str) -> JSONResponse | dict[str, object]:
    try:
        payload = await request.json()
        if not isinstance(payload, dict):
            raise ContractViolation("scenario payload must be an object")
        state = _facade(request).add_requirement_scenario(
            workspace_name,
            title=str(payload.get("title", "")),
            description=str(payload.get("description", "")),
            actors=payload.get("actors", ""),
            preconditions=payload.get("preconditions", ""),
            steps=payload.get("steps", ""),
            expected_outcomes=payload.get("expected_outcomes", ""),
            faults=payload.get("faults", ""),
            requirement_ids=payload.get("requirement_ids", ""),
        )
        scenario = state["scenarios"][-1]
        return {"status": "ok", "scenario": scenario}
    except (ContractViolation, RflpError, OSError, ValueError) as exc:
        return _error(exc)


@api_v1.get("/workspaces/{workspace_name}/scenarios", response_model=None)
def scenarios(request: Request, workspace_name: str) -> JSONResponse | dict[str, object]:
    try:
        state = _facade(request).requirements(workspace_name)
        if state is None:
            return _error(ContractViolation("requirements workbench is empty"), 404)
        return {
            "status": "ok",
            "scenarios": state.get("scenarios", ()),
            "runs": state.get("scenario_runs", ()),
        }
    except (ContractViolation, RflpError, OSError) as exc:
        return _error(exc, 404)


@api_v1.post("/workspaces/{workspace_name}/scenarios/{scenario_id}/execute", response_model=None)
def execute_scenario(request: Request, workspace_name: str, scenario_id: str) -> JSONResponse | dict[str, object]:
    try:
        return {"status": "ok", "execution": _facade(request).execute_requirement_scenario(workspace_name, scenario_id)}
    except (ContractViolation, RflpError, OSError) as exc:
        return _error(exc)


@api_v1.get("/workspaces/{workspace_name}/jobs/{job_id}", response_model=None)
def job(request: Request, workspace_name: str, job_id: str) -> JSONResponse | dict[str, object]:
    try:
        value = _facade(request).job(workspace_name, job_id)
        if value is None:
            return _error(ContractViolation("job not found"), 404)
        return {"status": "ok", "job": value}
    except (ContractViolation, RflpError, OSError) as exc:
        return _error(exc, 404)


@api_v1.get("/workspaces/{workspace_name}/profile", response_model=None)
def profile(request: Request, workspace_name: str) -> JSONResponse | dict[str, object]:
    try:
        return {"status": "ok", "profile": _facade(request).profile(workspace_name)}
    except (ContractViolation, RflpError, OSError) as exc:
        return _error(exc, 404)


@api_v1.put("/workspaces/{workspace_name}/profile", response_model=None)
async def update_profile(request: Request, workspace_name: str) -> JSONResponse | dict[str, object]:
    try:
        payload: Any = await request.json()
        return {"status": "ok", "profile": _facade(request).save_profile(workspace_name, payload)}
    except (ContractViolation, RflpError, OSError, ValueError) as exc:
        return _error(exc)


@api_v1.get("/workspaces/{workspace_name}/rflp", response_model=None)
def rflp(request: Request, workspace_name: str) -> JSONResponse | dict[str, object]:
    try:
        return {"status": "ok", "exchange": _facade(request).export_requirements_rflp(workspace_name)}
    except (ContractViolation, RflpError, OSError) as exc:
        return _error(exc, 404)


@api_v1.put("/workspaces/{workspace_name}/rflp", response_model=None)
async def update_rflp(request: Request, workspace_name: str) -> JSONResponse | dict[str, object]:
    try:
        payload = await request.json()
        state = _facade(request).import_requirements_rflp(workspace_name, payload)
        return {"status": "ok", "rflp": state["rflp"]}
    except (ContractViolation, RflpError, OSError, ValueError) as exc:
        return _error(exc)


@api_v1.get("/workspaces/{workspace_name}/rflp.sysml", response_model=None)
def rflp_sysml(request: Request, workspace_name: str) -> Response | JSONResponse:
    try:
        return Response(
            content=_facade(request).export_requirements_sysml_v2(workspace_name),
            media_type="text/plain",
        )
    except (ContractViolation, RflpError, OSError) as exc:
        return _error(exc, 404)


@api_v1.put("/workspaces/{workspace_name}/rflp.sysml", response_model=None)
async def update_rflp_sysml(request: Request, workspace_name: str) -> JSONResponse | dict[str, object]:
    try:
        text = (await request.body()).decode("utf-8")
        state = _facade(request).import_requirements_sysml_v2(workspace_name, text)
        return {"status": "ok", "rflp": state["rflp"]}
    except (ContractViolation, RflpError, OSError, UnicodeDecodeError) as exc:
        return _error(exc)


@api_v1.post("/workspaces/{workspace_name}/runs/{result_hash}/mlflow", response_model=None)
async def track_mlflow(request: Request, workspace_name: str, result_hash: str) -> JSONResponse | dict[str, object]:
    try:
        raw = await request.body()
        payload = json.loads(raw.decode("utf-8")) if raw else {}
        if not isinstance(payload, dict):
            raise ContractViolation("MLflow payload must be an object")
        return _facade(request).track_run_with_mlflow(
            workspace_name,
            result_hash,
            tracking_uri=payload.get("tracking_uri"),
            experiment_name=str(payload.get("experiment_name", "rflp-lite")),
        )
    except (ContractViolation, RflpError, OSError, ValueError, UnicodeDecodeError) as exc:
        return _error(exc)
