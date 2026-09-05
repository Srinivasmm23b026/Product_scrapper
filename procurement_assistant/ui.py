from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

ROOT = Path(__file__).parent
templates = Jinja2Templates(directory=ROOT / "templates")
react_index = ROOT / "static" / "app" / "index.html"
router = APIRouter(include_in_schema=False)


def react_or_legacy(request: Request, page_name: str):
    if react_index.is_file():
        return FileResponse(react_index)
    return templates.TemplateResponse(
        request,
        f"{page_name}.html",
        {"active_page": page_name, "title": page_name.title()},
    )


@router.get("/", response_class=HTMLResponse)
def home(request: Request):
    if react_index.is_file():
        return FileResponse(react_index)
    return RedirectResponse("/dashboard", status_code=302)


@router.get("/{page_name}", response_class=HTMLResponse)
def page(request: Request, page_name: str):
    allowed = {
        "dashboard",
        "compare",
        "inventory",
        "purchases",
        "spending",
        "settings",
        "login",
        "onboarding",
    }
    if page_name not in allowed:
        return templates.TemplateResponse(request, "404.html", status_code=404)
    return react_or_legacy(request, page_name)
