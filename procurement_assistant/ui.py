from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

ROOT = Path(__file__).parent
templates = Jinja2Templates(directory=ROOT / "templates")
router = APIRouter(include_in_schema=False)


@router.get("/", response_class=HTMLResponse)
def home():
    return RedirectResponse("/dashboard", status_code=302)


@router.get("/{page_name}", response_class=HTMLResponse)
def page(request: Request, page_name: str):
    allowed = {
        "dashboard",
        "compare",
        "inventory",
        "purchases",
        "spending",
        "login",
        "onboarding",
    }
    if page_name not in allowed:
        return templates.TemplateResponse(request, "404.html", status_code=404)
    return templates.TemplateResponse(
        request,
        f"{page_name}.html",
        {"active_page": page_name, "title": page_name.title()},
    )
