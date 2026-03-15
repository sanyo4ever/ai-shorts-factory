from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse, RedirectResponse


router = APIRouter(include_in_schema=False)
_UI_ROOT = Path(__file__).resolve().parent.parent / "ui"


@router.get("/")
def redirect_root() -> RedirectResponse:
    return RedirectResponse(url="/studio", status_code=307)


@router.get("/studio")
@router.get("/studio/")
def get_dashboard() -> FileResponse:
    return FileResponse(_UI_ROOT / "index.html")
