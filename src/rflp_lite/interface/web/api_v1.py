from __future__ import annotations

import json
import base64
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

from rflp_lite.domain.errors import ContractViolation, RflpError
from rflp_lite.interface.web.error_mapper import map_error
from rflp_lite.application.domain_packs import load_domain_pack, validate_domain_pack
from rflp_lite.application.discipline_batch import validate_evaluator_profile
from rflp_lite.application.resources import resource_path
from rflp_lite.application.scenarios import build_scenario


api_v1 = APIRouter(prefix="/api/v1", tags=["local-mvp"])


def _error(exc: Exception, status_code: int = 422) -> JSONResponse:
    mapped_status, mapped = map_error(exc)
    return JSONResponse(
        {
            "status": "failed",
            "error": type(exc).__name__,
            "message": str(exc),
            **mapped,
        },
        status_code=status_code if status_code != 422 or mapped_status == 500 else mapped_status,
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


@api_v1.post("/workspaces/{workspace_name}/concept-workflow", response_model=None)
@api_v1.post("/workspaces/{workspace_name}/concept-workflows", response_model=None)
async def create_concept_workflow(request: Request, workspace_name: str) -> JSONResponse | dict[str, object]:
    """Run the one-shot requirements-to-concept-design workflow."""

    try:
        payload = await request.json()
        if not isinstance(payload, Mapping):
            raise ContractViolation("concept workflow payload must be an object")
        raw_content = payload.get("content")
        text = str(payload.get("text", raw_content if isinstance(raw_content, str) else ""))
        document_bytes = None
        if payload.get("document_base64"):
            try:
                document_bytes = base64.b64decode(str(payload["document_base64"]), validate=True)
            except (ValueError, TypeError) as exc:
                raise ContractViolation("document_base64 is invalid") from exc
        raw_pack = payload.get("pack", "auto")
        pack = raw_pack if raw_pack is None or (isinstance(raw_pack, str) and raw_pack.strip().casefold() in {"", "auto"}) else _pack_payload(raw_pack)
        profile = _evaluator_profile_payload(payload.get("evaluator_profile", "development-v1"))
        seed = payload.get("seed", 42)
        if isinstance(seed, bool) or not isinstance(seed, int):
            raise ContractViolation("seed must be an integer")
        result = _facade(request).run_concept_workflow(
            workspace_name,
            text=text,
            filename=str(payload.get("filename", "requirements.txt")),
            document_bytes=document_bytes,
            pack=pack,
            evaluator_profile=profile,
            seed=seed,
            demo_mode=bool(payload.get("demo_mode", True)),
        )
        return {"status": "ok", "workflow": result}
    except (ContractViolation, RflpError, OSError, ValueError, UnicodeDecodeError) as exc:
        return _error(exc)


@api_v1.get("/workspaces/{workspace_name}/concept-workflow", response_model=None)
@api_v1.get("/workspaces/{workspace_name}/concept-workflows", response_model=None)
def get_latest_concept_workflow(request: Request, workspace_name: str) -> JSONResponse | dict[str, object]:
    try:
        return {"status": "ok", "workflow": _facade(request).concept_workflow(workspace_name)}
    except (ContractViolation, RflpError, OSError) as exc:
        return _error(exc, 404)


@api_v1.get("/workspaces/{workspace_name}/concept-workflow/{run_id}", response_model=None)
@api_v1.get("/workspaces/{workspace_name}/concept-workflows/{run_id}", response_model=None)
def get_concept_workflow(request: Request, workspace_name: str, run_id: str) -> JSONResponse | dict[str, object]:
    try:
        return {"status": "ok", "workflow": _facade(request).concept_workflow(workspace_name, run_id)}
    except (ContractViolation, RflpError, OSError) as exc:
        return _error(exc, 404)


@api_v1.post("/workspaces/{workspace_name}/concept-workflow/{run_id}/baseline", response_model=None)
@api_v1.post("/workspaces/{workspace_name}/concept-workflows/{run_id}/baseline", response_model=None)
async def select_concept_baseline(request: Request, workspace_name: str, run_id: str) -> JSONResponse | dict[str, object]:
    try:
        payload = await request.json()
        if not isinstance(payload, Mapping):
            raise ContractViolation("baseline selection payload must be an object")
        candidate_id = str(payload.get("candidate_id", "")).strip()
        if not candidate_id:
            raise ContractViolation("candidate_id is required")
        result = _facade(request).select_concept_baseline(
            workspace_name,
            run_id,
            candidate_id,
            selected_by=str(payload.get("selected_by", "user")),
            rationale=str(payload.get("rationale", "")),
        )
        return {"status": "ok", "baseline": result}
    except (ContractViolation, RflpError, OSError, ValueError) as exc:
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


@api_v1.post("/workspaces/{workspace_name}/requirements/reanalyze", response_model=None)
async def reanalyze_requirements_api(
    request: Request, workspace_name: str
) -> JSONResponse | dict[str, object]:
    """Queue a complete, reviewable analysis of the current requirement ledger."""

    try:
        try:
            payload = await request.json()
        except (json.JSONDecodeError, UnicodeDecodeError):
            payload = {}
        if payload is None:
            payload = {}
        if not isinstance(payload, Mapping):
            raise ContractViolation("reanalyze payload must be an object")
        mode = str(payload.get("mode", "full_reanalysis"))
        job = _facade(request).reanalyze_all_requirements(workspace_name, mode=mode)
        return {"status": "ok", "job": job}
    except (ContractViolation, RflpError, OSError, ValueError) as exc:
        return _error(exc)


@api_v1.get(
    "/workspaces/{workspace_name}/requirements/entities/{entity_type}/{entity_id}/delete-preview",
    response_model=None,
)
def preview_entity_delete_api(
    request: Request, workspace_name: str, entity_type: str, entity_id: str
) -> JSONResponse | dict[str, object]:
    try:
        preview = _facade(request).preview_entity_deletion(
            workspace_name, entity_type, entity_id
        )
        return {"status": "ok", "preview": preview}
    except (ContractViolation, RflpError, OSError, ValueError) as exc:
        return _error(exc, 404)


@api_v1.post(
    "/workspaces/{workspace_name}/requirements/entities/{entity_type}/{entity_id}/delete",
    response_model=None,
)
async def delete_entity_api(
    request: Request, workspace_name: str, entity_type: str, entity_id: str
) -> JSONResponse | dict[str, object]:
    try:
        payload = await request.json()
        if not isinstance(payload, Mapping):
            raise ContractViolation("delete payload must be an object")
        plan_hash = str(payload.get("plan_hash", ""))
        if not plan_hash:
            raise ContractViolation("plan_hash is required")
        state = _facade(request).delete_entity(
            workspace_name, entity_type, entity_id, plan_hash
        )
        return {"status": "ok", "requirements": state}
    except (ContractViolation, RflpError, OSError, ValueError) as exc:
        return _error(exc)


@api_v1.post(
    "/workspaces/{workspace_name}/requirements/entities/{entity_type}/{entity_id}/restore",
    response_model=None,
)
def restore_entity_api(
    request: Request, workspace_name: str, entity_type: str, entity_id: str
) -> JSONResponse | dict[str, object]:
    try:
        state = _facade(request).restore_entity(
            workspace_name, entity_type, entity_id
        )
        return {"status": "ok", "requirements": state}
    except (ContractViolation, RflpError, OSError, ValueError) as exc:
        return _error(exc)


@api_v1.post(
    "/workspaces/{workspace_name}/requirements/entities/delete-preview",
    response_model=None,
)
async def preview_entity_delete_api_body(
    request: Request, workspace_name: str
) -> JSONResponse | dict[str, object]:
    """Body-oriented alias used by the browser's generic entity controls."""

    try:
        payload = await request.json()
        if not isinstance(payload, Mapping):
            raise ContractViolation("delete preview payload must be an object")
        entity_type = str(payload.get("entity_type", ""))
        entity_id = str(payload.get("entity_id", ""))
        return {
            "status": "ok",
            "preview": _facade(request).preview_entity_deletion(
                workspace_name, entity_type, entity_id
            ),
        }
    except (ContractViolation, RflpError, OSError, ValueError) as exc:
        return _error(exc, 404)


@api_v1.post(
    "/workspaces/{workspace_name}/requirements/entities/delete",
    response_model=None,
)
async def delete_entity_api_body(
    request: Request, workspace_name: str
) -> JSONResponse | dict[str, object]:
    try:
        payload = await request.json()
        if not isinstance(payload, Mapping):
            raise ContractViolation("delete payload must be an object")
        state = _facade(request).delete_entity(
            workspace_name,
            str(payload.get("entity_type", "")),
            str(payload.get("entity_id", "")),
            str(payload.get("plan_hash", "")),
        )
        return {"status": "ok", "requirements": state}
    except (ContractViolation, RflpError, OSError, ValueError) as exc:
        return _error(exc)


@api_v1.post(
    "/workspaces/{workspace_name}/requirements/entities/restore",
    response_model=None,
)
async def restore_entity_api_body(
    request: Request, workspace_name: str
) -> JSONResponse | dict[str, object]:
    try:
        payload = await request.json()
        if not isinstance(payload, Mapping):
            raise ContractViolation("restore payload must be an object")
        state = _facade(request).restore_entity(
            workspace_name,
            str(payload.get("entity_type", "")),
            str(payload.get("entity_id", "")),
        )
        return {"status": "ok", "requirements": state}
    except (ContractViolation, RflpError, OSError, ValueError) as exc:
        return _error(exc)


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
        return {
            "status": "ok",
            "mbse": state["mbse"],
            "trace_links": state.get("trace_links", ()),
            "trace_diagnostics": state.get("trace_diagnostics", ()),
            "requirement_attributes": state.get("requirement_attributes", ()),
            "requirement_constraints": state.get("requirement_constraints", ()),
            "retrieval_suggestions": state.get("retrieval_suggestions", ()),
        }
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
            scenario_type=str(payload.get("scenario_type", "normal")),
            coverage_dimensions=payload.get("coverage_dimensions", ""),
            lifecycle_phase=str(payload.get("lifecycle_phase", "")),
            trigger=str(payload.get("trigger", "")),
            stakeholder_ids=payload.get("stakeholder_ids", ""),
            recovery_steps=payload.get("recovery_steps", ""),
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
            scenario_type=str(payload.get("scenario_type", "normal")),
            coverage_dimensions=payload.get("coverage_dimensions", ""),
            lifecycle_phase=str(payload.get("lifecycle_phase", "")),
            trigger=str(payload.get("trigger", "")),
            stakeholder_ids=payload.get("stakeholder_ids", ""),
            recovery_steps=payload.get("recovery_steps", ""),
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
        current = _facade(request).requirements(workspace_name) or {}
        existing = next(
            (
                item
                for item in current.get("scenarios", ())
                if isinstance(item, dict) and str(item.get("id")) == scenario_id
            ),
            None,
        )
        if existing is None:
            raise ContractViolation("场景不存在")
        state = _facade(request).revise_requirement_scenario(
            workspace_name,
            scenario_id,
            title=str(payload.get("title", existing.get("title", ""))),
            description=str(payload.get("description", existing.get("description", ""))),
            actors=payload.get("actors", existing.get("actors", "")),
            preconditions=payload.get("preconditions", existing.get("preconditions", "")),
            steps=payload.get("steps", existing.get("steps", "")),
            expected_outcomes=payload.get("expected_outcomes", existing.get("expected_outcomes", "")),
            faults=payload.get("faults", existing.get("faults", "")),
            requirement_ids=payload.get("requirement_ids", existing.get("requirement_ids", "")),
            scenario_type=(payload.get("scenario_type") if "scenario_type" in payload else None),
            coverage_dimensions=(payload.get("coverage_dimensions") if "coverage_dimensions" in payload else None),
            lifecycle_phase=(payload.get("lifecycle_phase") if "lifecycle_phase" in payload else None),
            trigger=(payload.get("trigger") if "trigger" in payload else None),
            stakeholder_ids=(payload.get("stakeholder_ids") if "stakeholder_ids" in payload else None),
            recovery_steps=(payload.get("recovery_steps") if "recovery_steps" in payload else None),
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


@api_v1.post(
    "/workspaces/{workspace_name}/stakeholders/{stakeholder_id}/edit",
    response_model=None,
)
async def edit_stakeholder_api(
    request: Request, workspace_name: str, stakeholder_id: str
) -> JSONResponse | dict[str, object]:
    try:
        payload = await request.json()
        if not isinstance(payload, Mapping):
            raise ContractViolation("stakeholder edit payload must be an object")
        allowed = {
            "name",
            "category",
            "description",
            "goals",
            "interactions",
            "requirement_ids",
            "scenario_ids",
            "aliases",
        }
        fields = {key: payload[key] for key in allowed if key in payload}
        if not fields:
            raise ContractViolation("stakeholder edit fields are required")
        state = _facade(request).edit_requirement_stakeholder(
            workspace_name, stakeholder_id, **fields
        )
        stakeholder = next(
            item
            for item in state.get("stakeholders", ())
            if isinstance(item, dict) and str(item.get("id")) == stakeholder_id
        )
        return {"status": "ok", "stakeholder": stakeholder}
    except (ContractViolation, RflpError, OSError, ValueError, StopIteration) as exc:
        return _error(exc)


@api_v1.post(
    "/workspaces/{workspace_name}/requirements/entities/{entity_type}/{entity_id}/edit",
    response_model=None,
)
async def edit_requirement_entity_api(
    request: Request, workspace_name: str, entity_type: str, entity_id: str
) -> JSONResponse | dict[str, object]:
    try:
        payload = await request.json()
        if not isinstance(payload, Mapping):
            raise ContractViolation("entity edit payload must be an object")
        if entity_type == "concern":
            fields = {
                key: payload[key]
                for key in ("name", "stakeholder_id")
                if key in payload
            }
        elif entity_type == "need":
            fields = {
                key: payload[key]
                for key in ("statement", "stakeholder_id", "concern_id")
                if key in payload
            }
        else:
            raise ContractViolation("只支持编辑 Concern 或 Need")
        state = _facade(request).edit_requirement_entity(
            workspace_name, entity_type, entity_id, **fields
        )
        group = "concerns" if entity_type == "concern" else "needs"
        item = next(
            value
            for value in state.get(group, ())
            if isinstance(value, dict) and str(value.get("id")) == entity_id
        )
        return {"status": "ok", "entity": item}
    except (ContractViolation, RflpError, OSError, ValueError, StopIteration) as exc:
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


@api_v1.get(
    "/workspaces/{workspace_name}/requirements/analysis-runs/{run_id}",
    response_model=None,
)
def analysis_run(
    request: Request, workspace_name: str, run_id: str
) -> JSONResponse | dict[str, object]:
    try:
        value = _facade(request).analysis_run(workspace_name, run_id)
        if value is None:
            return _error(ContractViolation("analysis run not found"), 404)
        return {"status": "ok", "run": value}
    except (ContractViolation, RflpError, OSError) as exc:
        return _error(exc, 404)


@api_v1.post(
    "/workspaces/{workspace_name}/requirements/analysis-runs/{run_id}/retry-failed",
    response_model=None,
)
def retry_failed_analysis(
    request: Request, workspace_name: str, run_id: str
) -> JSONResponse | dict[str, object]:
    try:
        return {
            "status": "ok",
            "run": _facade(request).retry_failed_analysis(workspace_name, run_id),
        }
    except (ContractViolation, RflpError, OSError) as exc:
        return _error(exc, 404)


@api_v1.post(
    "/workspaces/{workspace_name}/requirements/analysis/blocks/{block_id}",
    response_model=None,
)
async def retry_analysis_block(
    request: Request, workspace_name: str, block_id: str
) -> JSONResponse | dict[str, object]:
    try:
        payload = await request.json()
        payload = payload if isinstance(payload, dict) else {}
        state = _facade(request).requirements(workspace_name)
        run_id = str(payload.get("run_id") or ((state or {}).get("auto_analysis") or {}).get("job_id", ""))
        if not run_id:
            raise ContractViolation("当前工作区没有可重试的分析 Job")
        return {
            "status": "ok",
            "run": _facade(request).retry_requirement_enrichment_block(
                workspace_name, run_id, block_id
            ),
        }
    except (ContractViolation, RflpError, OSError, ValueError, json.JSONDecodeError) as exc:
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
