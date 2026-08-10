"""Admin panel auth: bot-issued one-time login link + a signed session cookie.

No domain/HTTPS needed (unlike Telegram's Login Widget, which requires a
BotFather-registered domain) — the bot itself vouches for the telegram_id via
the long-polling connection it already has, same trust root as everything
else in this bot. /admin in the chat gets you a short-lived signed link.
"""

import hashlib
import hmac
import time

from fastapi import HTTPException, Request

from app.config import get_settings

COOKIE_NAME = "admin_session"
SESSION_MAX_AGE_S = 30 * 24 * 3600
LOGIN_TOKEN_MAX_AGE_S = 5 * 60


class InvalidLogin(Exception):
    pass


def _session_secret() -> str:
    settings = get_settings()
    return settings.admin_session_secret or settings.bot_token


def sign_session(telegram_id: int) -> str:
    expires = int(time.time()) + SESSION_MAX_AGE_S
    payload = f"{telegram_id}.{expires}"
    sig = hmac.new(_session_secret().encode(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}.{sig}"


def verify_session(token: str) -> int:
    try:
        tid_s, expires_s, sig = token.split(".")
    except ValueError as e:
        raise InvalidLogin("malformed session") from e
    payload = f"{tid_s}.{expires_s}"
    expected = hmac.new(_session_secret().encode(), payload.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, sig):
        raise InvalidLogin("bad session signature")
    if int(expires_s) < time.time():
        raise InvalidLogin("session expired")
    return int(tid_s)


def sign_login_token(telegram_id: int) -> str:
    """Short-lived, single-purpose token for the /admin bot command's link.

    Same tid.expires.sig shape as a session cookie, but signed over a
    "login."-prefixed payload so one can never be mistaken for the other.
    """
    expires = int(time.time()) + LOGIN_TOKEN_MAX_AGE_S
    payload = f"login.{telegram_id}.{expires}"
    sig = hmac.new(_session_secret().encode(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{telegram_id}.{expires}.{sig}"


def verify_login_token(token: str) -> int:
    try:
        tid_s, expires_s, sig = token.split(".")
    except ValueError as e:
        raise InvalidLogin("malformed token") from e
    payload = f"login.{tid_s}.{expires_s}"
    expected = hmac.new(_session_secret().encode(), payload.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, sig):
        raise InvalidLogin("bad token signature")
    if int(expires_s) < time.time():
        raise InvalidLogin("token expired")
    return int(tid_s)


def admin_ids() -> set[int]:
    raw = get_settings().admin_ids
    return {int(x) for x in raw.split(",") if x.strip()}


def session_from_request(request: Request) -> int | None:
    """Return the logged-in admin's telegram_id, or None if not authenticated."""
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return None
    try:
        telegram_id = verify_session(token)
    except InvalidLogin:
        return None
    if telegram_id not in admin_ids():
        return None
    return telegram_id


def require_admin(request: Request) -> int:
    telegram_id = session_from_request(request)
    if telegram_id is None:
        raise HTTPException(401, "not logged in")
    return telegram_id
