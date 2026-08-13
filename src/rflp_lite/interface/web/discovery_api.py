"""Thin JSON API for intelligent MBSE discovery."""

from __future__ import annotations

from collections.abc import Mapping

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from rflp_lite.domain.errors import ContractViolation, RflpError


discovery_api = APIRouter(prefix="/api/v1/workspaces/{workspace_name}/discovery", tags=["discovery"])


def _error(exc: Exception, status_code: int = 422) -> JSONResponse:
    return JSONResponse({"status": "failed", "error": type(exc).__name__, "message": str(exc)}, status_code=status_code)


@discovery_api.post("/draft")
async def draft(request: Request, workspace_name: str):
    try:
        payload = await request.json()
        pack_id = str(payload.get("pack_id", "urban-medical-aam-v1")) if isinstance(payload, Mapping) else "urban-medical-aam-v1"
        return {"status": "ok", **request.app.state.facade.draft_discovery(workspace_name, pack_id)}
    except (ContractViolation, RflpError, OSError, ValueError) as exc:
        return _error(exc)


@discovery_api.post("/review")
async def review(request: Request, workspace_name: str):
    try:
        payload = await request.json()
        if not isinstance(payload, Mapping):
            raise ContractViolation("review payload must be an object")
        result = request.app.state.facade.review_discovery(workspace_name, str(payload.get("candidate_id", "")), str(payload.get("decision", "")), int(payload.get("expected_revision", -1)), str(payload.get("pack_id", "urban-medical-aam-v1")))
        return {"status": "ok", **result}
    except (ContractViolation, RflpError, OSError, ValueError) as exc:
        return _error(exc)


@discovery_api.post("/edit")
async def edit(request: Request, workspace_name: str):
    try:
        payload = await request.json()
        if not isinstance(payload, Mapping) or not isinstance(payload.get("payload"), Mapping):
            raise ContractViolation("edit payload must contain an object payload")
        result = request.app.state.facade.edit_discovery(workspace_name, str(payload.get("candidate_id", "")), dict(payload["payload"]), int(payload.get("expected_revision", -1)), str(payload.get("pack_id", "urban-medical-aam-v1")))
        return {"status": "ok", **result}
    except (ContractViolation, RflpError, OSError, ValueError) as exc:
        return _error(exc)


@discovery_api.post("/finalize")
async def finalize(request: Request, workspace_name: str):
    try:
        payload = await request.json()
        pack_id = str(payload.get("pack_id", "urban-medical-aam-v1")) if isinstance(payload, Mapping) else "urban-medical-aam-v1"
        return {"status": "ok", **request.app.state.facade.finalize_discovery(workspace_name, pack_id)}
    except (ContractViolation, RflpError, OSError, ValueError) as exc:
        return _error(exc)
