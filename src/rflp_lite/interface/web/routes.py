from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from rflp_lite.interface.web.presenters import page_context


router = APIRouter()
templates = Jinja2Templates(directory=Path(__file__).resolve().parent / "templates")


@router.get("/", response_class=HTMLResponse)
def dashboard(request: Request) -> HTMLResponse:
    view = request.app.state.facade.dashboard(None)
    context = page_context(
        view["workspace"],
        workspaces=view["workspaces"],
        latest_run=view["latest_run"],
        counts=view["counts"],
        audit=view["audit"],
    )
    return templates.TemplateResponse(request=request, name="dashboard.html", context=context)
