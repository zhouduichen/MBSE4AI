from __future__ import annotations

import json
import base64
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

from rflp_lite.domain.errors import ContractViolation, RflpError
from rflp_lite.application.domain_packs import load_domain_pack, validate_domain_pack
from rflp_lite.application.discipline_batch import validate_evaluator_profile
from rflp_lite.application.resources import resource_path
from rflp_lite.application.scenarios import build_scenario


api_v1 = APIRouter(prefix="/api/v1", tags=["local-mvp"])


def _error(exc: Exception, status_code: int = 422) -> JSONResponse:
    return JSONResponse(
        {"status": "failed", "error": type(exc).__name__, "message": str(exc)},
        status_code=status_code,
    )


def _facade(request: Request):
    return request.app.state.facade


def _pack_payload(value: object) -> dict[str, object]:
    """Resolve a pack object or a packaged alias at the HTTP boundary.

    The Web API deliberately does not accept arbitrary server paths.  Pack
    uploads use an object payload; string values are limited to the packaged
    domain-pack directory (for example ``fixed-wing-v1``).
    """

    if isinstance(value, Mapping):
        return validate_domain_pack(dict(value))
    if not isinstance(value, str) or not value.strip():
        raise ContractViolation("domain pack must be an object or packaged alias")
    identifier = value.strip()
    if any(part in identifier for part in ("/", "\\")) or Path(identifier).is_absolute():
        raise ContractViolation("Web API domain-pack paths are not allowed")
    filename = identifier if identifier.endswith(".json") else f"{identifier}.json"
    path = resource_path(f"domain-packs/{filename}")
    return load_domain_pack(path)


def _evaluator_profile_payload(value: object) -> dict[str, object]:
    """Resolve an evaluator profile object or packaged development fixture."""

    if isinstance(value, Mapping):
        return validate_evaluator_profile(dict(value))
    if not isinstance(value, str) or not value.strip():
        raise ContractViolation("evaluator_profile must be an object or packaged alias")
    identifier = value.strip()
    if any(part in identifier for part in ("/", "\\")) or Path(identifier).is_absolute():
        raise ContractViolation("Web API evaluator-profile paths are not allowed")
    aliases = {
        "development-v1": "development-evaluator-profile.json",
        "development-evaluator-profile": "development-evaluator-profile.json",
    }
    filename = aliases.get(identifier, identifier if identifier.endswith(".json") else f"{identifier}.json")
    path = resource_path(f"examples/concept-design/{filename}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        if identifier == "development-v1":
            return {"id": "development-v1", "version": 1, "approvals": {}}
        raise ContractViolation(f"evaluator profile not found: {identifier}") from exc
    return validate_evaluator_profile(payload)


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


@api_v1.post("/workspaces/{workspace_name}/domain-packs/validate", response_model=None)
async def validate_concept_pack(request: Request, workspace_name: str) -> JSONResponse | dict[str, object]:
    try:
        payload = await request.json()
        if not isinstance(payload, Mapping):
            raise ContractViolation("domain pack payload must be an object")
        pack = payload.get("pack", payload)
        return {"status": "ok", "pack": _pack_payload(pack)}
    except (ContractViolation, RflpError, OSError, ValueError, UnicodeDecodeError) as exc:
        return _error(exc)


@api_v1.post("/workspaces/{workspace_name}/schemes/import", response_model=None)
async def import_concept_schemes(request: Request, workspace_name: str) -> JSONResponse | dict[str, object]:
    try:
        payload = await request.json()
        if not isinstance(payload, Mapping):
            raise ContractViolation("scheme import payload must be an object")
        content = payload.get("content")
        if isinstance(content, str) and len(content.encode("utf-8")) > 50 * 1024 * 1024:
            raise ContractViolation("scheme import exceeds 50 MiB")
        if isinstance(content, (bytes, bytearray)) and len(content) > 50 * 1024 * 1024:
            raise ContractViolation("scheme import exceeds 50 MiB")
        filename = str(payload.get("filename", "schemes.json"))
        pack = _pack_payload(payload.get("pack"))
        result = _facade(request).import_concept_schemes(workspace_name, pack, content, filename)
        return {"status": "ok", "import": result}
    except (ContractViolation, RflpError, OSError, ValueError, UnicodeDecodeError) as exc:
        return _error(exc)


@api_v1.post("/workspaces/{workspace_name}/concept-runs", response_model=None)
async def create_concept_run(request: Request, workspace_name: str) -> JSONResponse | dict[str, object]:
    try:
        payload = await request.json()
        if not isinstance(payload, Mapping):
            raise ContractViolation("concept run payload must be an object")
        envelope = payload.get("envelope")
        if not isinstance(envelope, Mapping):
            raise ContractViolation("concept run envelope must be an object")
        pack = _pack_payload(payload.get("pack"))
        profile = _evaluator_profile_payload(payload.get("evaluator_profile", "development-v1"))
        result = _facade(request).run_concept_design(
            workspace_name,
            pack,
            profile,
            dict(envelope),
            optimize=bool(payload.get("optimize", True)),
        )
        return {"status": "ok", "run": result}
    except (ContractViolation, RflpError, OSError, ValueError, UnicodeDecodeError) as exc:
        return _error(exc)


@api_v1.get("/workspaces/{workspace_name}/concept-runs/{run_id}", response_model=None)
def get_concept_run(request: Request, workspace_name: str, run_id: str) -> JSONResponse | dict[str, object]:
    try:
        return {"status": "ok", "run": _facade(request).concept_run(workspace_name, run_id)}
    except (ContractViolation, RflpError, OSError) as exc:
        return _error(exc, 404)


@api_v1.post("/workspaces/{workspace_name}/concept-runs/{run_id}/evaluate", response_model=None)
def evaluate_concept_run(request: Request, workspace_name: str, run_id: str) -> JSONResponse | dict[str, object]:
    try:
        return {"status": "ok", "run": _facade(request).concept_run(workspace_name, run_id)}
    except (ContractViolation, RflpError, OSError) as exc:
        return _error(exc, 404)


@api_v1.post("/workspaces/{workspace_name}/concept-runs/{run_id}/optimize", response_model=None)
def optimize_concept_run(request: Request, workspace_name: str, run_id: str) -> JSONResponse | dict[str, object]:
    try:
        return {"status": "ok", "run": _facade(request).concept_run(workspace_name, run_id)}
    except (ContractViolation, RflpError, OSError) as exc:
        return _error(exc, 404)


@api_v1.post("/workspaces/{workspace_name}/layout-candidates/{candidate_id}/review", response_model=None)
async def review_concept_candidate(request: Request, workspace_name: str, candidate_id: str) -> JSONResponse | dict[str, object]:
    try:
        payload = await request.json()
        if not isinstance(payload, Mapping):
            raise ContractViolation("candidate review payload must be an object")
        decision = str(payload.get("decision", ""))
        return {"status": "ok", "review": _facade(request).review_layout_candidate(workspace_name, candidate_id, decision, str(payload.get("run_id", "")))}
    except (ContractViolation, RflpError, OSError, ValueError) as exc:
        return _error(exc)


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


@api_v1.get("/workspaces/{workspace_name}/requirements/analysis-config", response_model=None)
def requirements_analysis_config(
    request: Request, workspace_name: str
) -> JSONResponse | dict[str, object]:
    try:
        facade = _facade(request)
        return {
            "status": "ok",
            "config": facade.analysis_config(workspace_name),
            "available_domain_packs": facade.available_analysis_domain_packs(),
        }
    except (ContractViolation, RflpError, OSError) as exc:
        return _error(exc, 404)


@api_v1.put("/workspaces/{workspace_name}/requirements/analysis-config", response_model=None)
async def save_requirements_analysis_config(
    request: Request, workspace_name: str
) -> JSONResponse | dict[str, object]:
    try:
        payload = await request.json()
        if not isinstance(payload, Mapping):
            raise ContractViolation("分析配置必须是对象")
        state = _facade(request).save_analysis_config(workspace_name, dict(payload))
        return {
            "status": "ok",
            "config": state.get("analysis_config"),
            "requirements": state,
        }
    except (ContractViolation, RflpError, OSError, ValueError) as exc:
        return _error(exc)


@api_v1.get("/workspaces/{workspace_name}/requirements/overview", response_model=None)
def requirements_overview(request: Request, workspace_name: str) -> JSONResponse | dict[str, object]:
    try:
        return {"status": "ok", "overview": _facade(request).requirement_overview(workspace_name)}
    except (ContractViolation, RflpError, OSError) as exc:
        return _error(exc, 404)


@api_v1.post("/workspaces/{workspace_name}/requirements/run-flow", response_model=None)
def run_requirements_flow(request: Request, workspace_name: str) -> JSONResponse | dict[str, object]:
    try:
        state = _facade(request).run_requirements_flow(workspace_name)
        return {"status": "ok", "flow": state.get("flow"), "requirements": state}
    except (ContractViolation, RflpError, OSError, ValueError) as exc:
        return _error(exc)


@api_v1.post("/workspaces/{workspace_name}/requirements/implicit-constraints", response_model=None)
def suggest_implicit_constraints(request: Request, workspace_name: str) -> JSONResponse | dict[str, object]:
    try:
        state = _facade(request).suggest_implicit_requirements(workspace_name)
        return {"status": "ok", "requirements": state.get("structured_requirements", ()), "workbench": state}
    except (ContractViolation, RflpError, OSError, ValueError) as exc:
        return _error(exc)


@api_v1.post("/workspaces/{workspace_name}/requirements/mbse", response_model=None)
def generate_mbse(request: Request, workspace_name: str) -> JSONResponse | dict[str, object]:
    try:
        state = _facade(request).generate_requirements_mbse(workspace_name)
        return {"status": "ok", "mbse": state.get("mbse"), "requirements": state}
    except (ContractViolation, RflpError, OSError, ValueError) as exc:
        return _error(exc)


@api_v1.post("/workspaces/{workspace_name}/requirements/mbse/edit", response_model=None)
async def edit_mbse(request: Request, workspace_name: str) -> JSONResponse | dict[str, object]:
    try:
        payload = await request.json()
        if not isinstance(payload, dict):
            raise ContractViolation("MBSE edit payload must be an object")
        revision = str(payload.get("revision", payload.get("expected_revision", "")))
        operation = payload.get("operation", payload)
        if not isinstance(operation, dict):
            raise ContractViolation("MBSE edit operation must be an object")
        state = _facade(request).edit_requirements_mbse(workspace_name, revision, operation)
        return {"status": "ok", "mbse": state.get("mbse"), "requirements": state}
    except (ContractViolation, RflpError, OSError, ValueError) as exc:
        return _error(exc)


@api_v1.post("/workspaces/{workspace_name}/requirements/mbse/review", response_model=None)
async def review_mbse_element(request: Request, workspace_name: str) -> JSONResponse | dict[str, object]:
    try:
        payload = await request.json()
        if not isinstance(payload, dict):
            raise ContractViolation("MBSE review payload must be an object")
        state = _facade(request).review_requirements_mbse_element(
            workspace_name,
            str(payload.get("element_id", "")),
            str(payload.get("decision", "")),
        )
        return {"status": "ok", "mbse": state.get("mbse"), "requirements": state}
    except (ContractViolation, RflpError, OSError, ValueError) as exc:
        return _error(exc)


@api_v1.post("/workspaces/{workspace_name}/requirements/mbse/confirm", response_model=None)
def confirm_mbse(request: Request, workspace_name: str) -> JSONResponse | dict[str, object]:
    try:
        state = _facade(request).confirm_requirements_mbse(workspace_name)
        return {"status": "ok", "mbse": state.get("mbse"), "requirements": state}
    except (ContractViolation, RflpError, OSError, ValueError) as exc:
        return _error(exc)


@api_v1.get("/workspaces/{workspace_name}/requirements/mbse", response_model=None)
def mbse(request: Request, workspace_name: str) -> JSONResponse | dict[str, object]:
    try:
        state = _facade(request).requirements(workspace_name)
        if not state or not state.get("mbse"):
            return _error(ContractViolation("MBSE semantic model not generated"), 404)
        return {"status": "ok", "mbse": state["mbse"], "trace_links": state.get("trace_links", ())}
    except (ContractViolation, RflpError, OSError) as exc:
        return _error(exc, 404)


@api_v1.get("/workspaces/{workspace_name}/requirements/mbse/views", response_model=None)
def mbse_views(request: Request, workspace_name: str) -> JSONResponse | dict[str, object]:
    try:
        return {
            "status": "ok",
            "views": _facade(request).mbse_views(workspace_name),
        }
    except (ContractViolation, RflpError, OSError) as exc:
        return _error(exc, 404)


@api_v1.get("/workspaces/{workspace_name}/requirements/mbse/views/{view_id}", response_model=None)
def mbse_view(
    request: Request,
    workspace_name: str,
    view_id: str,
    engine: str = "auto",
    format: str = "svg",
) -> JSONResponse | dict[str, object]:
    try:
        result = _facade(request).render_requirements_mbse_view(
            workspace_name,
            view_id,
            engine=engine,
            output_format=format,
        )
        content = result.pop("content")
        if not isinstance(content, bytes):
            raise ContractViolation("diagram renderer returned invalid content")
        result["content"] = (
            content.decode("utf-8", errors="replace")
            if result.get("media_type") == "image/svg+xml"
            else base64.b64encode(content).decode("ascii")
        )
        return {"status": "ok", "view": result}
    except (ContractViolation, RflpError, OSError, ValueError) as exc:
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
        created_id = build_scenario(
            title=str(payload.get("title", "")),
            description=str(payload.get("description", "")),
            actors=payload.get("actors", ""),
            preconditions=payload.get("preconditions", ""),
            steps=payload.get("steps", ""),
            expected_outcomes=payload.get("expected_outcomes", ""),
            faults=payload.get("faults", ""),
            requirement_ids=payload.get("requirement_ids", ""),
        )["id"]
        scenario = next(item for item in state["scenarios"] if item["id"] == created_id)
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


@api_v1.get("/workspaces/{workspace_name}/scenarios/{scenario_id}/sequence", response_model=None)
def scenario_sequence(
    request: Request, workspace_name: str, scenario_id: str
) -> JSONResponse | dict[str, object]:
    try:
        result = _facade(request).sequence_diagram(workspace_name, scenario_id)
        return {
            "status": "ok",
            "scenario": result["scenario"],
            "interaction": result["interaction"],
            "layout": result["layout"],
            "svg": result["svg"],
            "warnings": result["warnings"],
        }
    except (ContractViolation, RflpError, OSError, ValueError) as exc:
        return _error(exc, 404)


@api_v1.post("/workspaces/{workspace_name}/scenarios/{scenario_id}/edit", response_model=None)
async def edit_scenario(request: Request, workspace_name: str, scenario_id: str) -> JSONResponse | dict[str, object]:
    try:
        payload = await request.json()
        if not isinstance(payload, dict):
            raise ContractViolation("scenario edit payload must be an object")
        state = _facade(request).revise_requirement_scenario(
            workspace_name,
            scenario_id,
            title=str(payload.get("title", "")),
            description=str(payload.get("description", "")),
            actors=payload.get("actors", ""),
            preconditions=payload.get("preconditions", ""),
            steps=payload.get("steps", ""),
            expected_outcomes=payload.get("expected_outcomes", ""),
            faults=payload.get("faults", ""),
            requirement_ids=payload.get("requirement_ids", ""),
        )
        scenario = next(item for item in state["scenarios"] if item["id"] == scenario_id)
        return {"status": "ok", "scenario": scenario}
    except (ContractViolation, RflpError, OSError, ValueError) as exc:
        return _error(exc)


@api_v1.post("/workspaces/{workspace_name}/scenarios/{scenario_id}/review", response_model=None)
async def review_scenario(request: Request, workspace_name: str, scenario_id: str) -> JSONResponse | dict[str, object]:
    try:
        payload = await request.json()
        if not isinstance(payload, dict):
            raise ContractViolation("scenario review payload must be an object")
        state = _facade(request).review_requirement_scenario(
            workspace_name, scenario_id, str(payload.get("decision", ""))
        )
        scenario = next(item for item in state["scenarios"] if item["id"] == scenario_id)
        return {"status": "ok", "scenario": scenario}
    except (ContractViolation, RflpError, OSError, ValueError) as exc:
        return _error(exc)


@api_v1.post("/workspaces/{workspace_name}/stakeholders", response_model=None)
async def add_stakeholder(request: Request, workspace_name: str) -> JSONResponse | dict[str, object]:
    try:
        payload = await request.json()
        if not isinstance(payload, dict):
            raise ContractViolation("stakeholder payload must be an object")
        state = _facade(request).add_requirement_stakeholder(
            workspace_name,
            str(payload.get("name", "")),
            str(payload.get("category", "")),
        )
        stakeholder = next(
            item
            for item in state["stakeholders"]
            if item["name"].casefold() == str(payload.get("name", "")).strip().casefold()
        )
        return {"status": "ok", "stakeholder": stakeholder}
    except (ContractViolation, RflpError, OSError, ValueError) as exc:
        return _error(exc)


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


@api_v1.post(
    "/workspaces/{workspace_name}/requirements/enrichment/{job_id}/retry",
    response_model=None,
)
def retry_requirement_enrichment(
    request: Request, workspace_name: str, job_id: str
) -> JSONResponse | dict[str, object]:
    try:
        return {
            "status": "ok",
            "job": _facade(request).retry_requirement_enrichment(workspace_name, job_id),
        }
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


@api_v1.post("/workspaces/{workspace_name}/requirements/generate-draft", response_model=None)
def generate_requirements_draft(request: Request, workspace_name: str) -> JSONResponse | dict[str, object]:
    try:
        state = _facade(request).generate_requirements_draft(workspace_name)
        return {
            "status": "ok",
            "draft": True,
            "rflp": state.get("rflp"),
            "draft_graph": state.get("draft_graph"),
            "svg": state.get("svg", ""),
        }
    except (ContractViolation, RflpError, OSError) as exc:
        return _error(exc)


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
