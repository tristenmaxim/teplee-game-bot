"""Admin panel: bot-text editor UI. Auth via a link the bot sends on /admin."""

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel

from app.admin_auth import (
    COOKIE_NAME,
    SESSION_MAX_AGE_S,
    InvalidLogin,
    admin_ids,
    require_admin,
    session_from_request,
    sign_session,
    verify_login_token,
)
from app.db import Database
from app.services import texts

router = APIRouter()
STATIC_DIR = Path(__file__).parent / "admin_static"


def get_db(request: Request) -> Database:
    return request.app.state.db


@router.get("/admin/login", response_model=None)
async def admin_login_page(request: Request) -> HTMLResponse | RedirectResponse:
    if session_from_request(request) is not None:
        return RedirectResponse(url="/admin/")
    html = (STATIC_DIR / "login.html").read_text(encoding="utf-8")
    return HTMLResponse(html)


@router.get("/admin/auth/token")
async def admin_auth_token(request: Request, token: str) -> RedirectResponse:
    try:
        telegram_id = verify_login_token(token)
    except InvalidLogin as e:
        raise HTTPException(401, str(e)) from e
    if telegram_id not in admin_ids():
        raise HTTPException(403, "not an admin")

    response = RedirectResponse(url="/admin/")
    response.set_cookie(
        COOKIE_NAME,
        sign_session(telegram_id),
        httponly=True,
        samesite="lax",
        secure=request.url.scheme == "https",
        max_age=SESSION_MAX_AGE_S,
    )
    return response


@router.get("/admin/logout")
async def admin_logout() -> RedirectResponse:
    response = RedirectResponse(url="/admin/login")
    response.delete_cookie(COOKIE_NAME)
    return response


@router.get("/admin/", response_model=None)
async def admin_index(request: Request) -> HTMLResponse | RedirectResponse:
    if session_from_request(request) is None:
        return RedirectResponse(url="/admin/login")
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    return HTMLResponse(html)


@router.get("/admin/api/texts")
async def api_list_texts(_admin_id: Annotated[int, Depends(require_admin)]) -> list[dict]:
    return texts.list_texts()


class TextUpdate(BaseModel):
    value: str


@router.put("/admin/api/texts/{key}")
async def api_update_text(
    key: str,
    body: TextUpdate,
    db: Annotated[Database, Depends(get_db)],
    _admin_id: Annotated[int, Depends(require_admin)],
) -> dict:
    if key not in texts.DEFAULTS:
        raise HTTPException(404, "unknown key")
    try:
        await texts.set_text(db, key, body.value)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    return {"key": key, "value": body.value}


@router.post("/admin/api/texts/{key}/reset")
async def api_reset_text(
    key: str,
    db: Annotated[Database, Depends(get_db)],
    _admin_id: Annotated[int, Depends(require_admin)],
) -> dict:
    if key not in texts.DEFAULTS:
        raise HTTPException(404, "unknown key")
    value = await texts.reset_text(db, key)
    return {"key": key, "value": value}
