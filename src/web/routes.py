from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from src.config import settings

router = APIRouter()

BASE_DIR = Path(__file__).resolve().parent.parent.parent
templates = Jinja2Templates(directory=BASE_DIR / "templates")

ASSET_VERSION = "1"


def mount_static(app) -> None:
    app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")


@router.get("/", response_class=HTMLResponse)
@router.get("/lists/{rest:path}", response_class=HTMLResponse)
async def index(request: Request, rest: str = ""):
    return templates.TemplateResponse(
        request,
        "index.html",
        {"asset_version": ASSET_VERSION, "auth_enabled": settings.auth_enabled},
    )
