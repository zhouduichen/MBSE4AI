"""FastAPI composition root for resource-oriented Harness v2 pages/API."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from rflp_lite.application.resources import default_workspace_root
from rflp_lite.bootstrap.container import ApplicationContainer, build_container
from rflp_lite.domain.errors import ContractViolation, NotFoundError, RflpError
from rflp_lite.interface.web.resource_api import resource_api
from rflp_lite.interface.web.resource_pages import resource_pages


def create_app(
    workspace_root: Path | None = None,
    fixture_root: Path | None = None,
    container: ApplicationContainer | None = None,
) -> FastAPI:
    root = (workspace_root or default_workspace_root()).resolve()
    application_container = container or build_container(root, fixture_root)
    app = FastAPI(title="AI4MBSE Harness", docs_url=None, redoc_url=None)
    app.state.container = application_container
    static_dir = Path(__file__).resolve().parent / "static"
    if static_dir.is_dir():
        app.mount("/static", StaticFiles(directory=static_dir), name="static")
    app.include_router(resource_api)
    app.include_router(resource_pages)

    @app.get("/", include_in_schema=False)
    async def root_redirect() -> RedirectResponse:
        return RedirectResponse("/ui/projects", status_code=303)

    @app.exception_handler(ContractViolation)
    async def contract_error(_request: Request, exc: ContractViolation) -> JSONResponse:
        return JSONResponse({"status": "failed", "error": type(exc).__name__, "message": str(exc)}, status_code=422)

    @app.exception_handler(NotFoundError)
    async def not_found_error(_request: Request, exc: NotFoundError) -> JSONResponse:
        return JSONResponse({"status": "failed", "error": type(exc).__name__, "message": str(exc)}, status_code=404)

    @app.exception_handler(RflpError)
    async def application_error(_request: Request, exc: RflpError) -> JSONResponse:
        return JSONResponse({"status": "failed", "error": type(exc).__name__, "message": str(exc)}, status_code=422)

    return app
