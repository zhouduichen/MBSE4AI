from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from rflp_lite.application.resources import default_workspace_root
from rflp_lite.application.web_facade import WebFacade
from rflp_lite.domain.errors import ContractViolation, RflpError
from rflp_lite.interface.web.routes import router, templates
from rflp_lite.interface.web.api_v1 import api_v1
from rflp_lite.interface.web.discovery_api import discovery_api
from rflp_lite.interface.web.discovery_routes import discovery_router


def create_app(
    workspace_root: Path | None = None,
    fixture_root: Path | None = None,
) -> FastAPI:
    package_dir = Path(__file__).resolve().parent
    root = (workspace_root or default_workspace_root()).resolve()
    app = FastAPI(
        title="RFLP-Lite Local Console",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.facade = WebFacade(root, fixture_root)
    app.mount("/static", StaticFiles(directory=package_dir / "static"), name="static")
    app.include_router(router)
    app.include_router(api_v1)
    app.include_router(discovery_router)
    app.include_router(discovery_api)

    @app.exception_handler(ContractViolation)
    async def contract_error(request: Request, exc: ContractViolation) -> HTMLResponse:
        return templates.TemplateResponse(
            request=request,
            name="error.html",
            context={"message": str(exc), "status_code": 404, "workspace": None},
            status_code=404,
        )

    @app.exception_handler(RflpError)
    async def application_error(request: Request, exc: RflpError) -> HTMLResponse:
        return templates.TemplateResponse(
            request=request,
            name="error.html",
            context={"message": str(exc), "status_code": 422, "workspace": None},
            status_code=422,
        )

    return app
