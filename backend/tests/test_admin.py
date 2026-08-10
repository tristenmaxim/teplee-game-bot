import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.admin_auth import (
    COOKIE_NAME,
    InvalidLogin,
    sign_login_token,
    sign_session,
    verify_login_token,
    verify_session,
)
from app.main import app
from app.services import texts

# --- bot-issued one-time login token ---

def test_login_token_roundtrip():
    token = sign_login_token(42)
    assert verify_login_token(token) == 42


def test_login_token_rejects_tampered_id():
    token = sign_login_token(42)
    _tid, expires, sig = token.split(".")
    tampered = f"999.{expires}.{sig}"
    with pytest.raises(InvalidLogin):
        verify_login_token(tampered)


def test_login_token_rejects_malformed_token():
    with pytest.raises(InvalidLogin):
        verify_login_token("not-a-token")


def test_login_token_cannot_be_used_as_session():
    # different signed payload ("login." prefix) — a leaked short-lived login
    # link must not double as a 30-day session cookie
    token = sign_login_token(42)
    with pytest.raises(InvalidLogin):
        verify_session(token)


# --- session cookie signing ---

def test_session_roundtrip():
    token = sign_session(42)
    assert verify_session(token) == 42


def test_session_rejects_tampered_signature():
    token = sign_session(42)
    tampered = token.rsplit(".", 1)[0] + ".deadbeef"
    with pytest.raises(InvalidLogin):
        verify_session(tampered)


def test_session_rejects_malformed_token():
    with pytest.raises(InvalidLogin):
        verify_session("not-a-session-token")


# --- texts service ---

async def test_texts_set_get_reset_roundtrip(db):
    await texts.init_cache(db)
    default = texts.DEFAULTS["word_not_found"]
    assert texts.get("word_not_found") == default

    await texts.set_text(db, "word_not_found", "custom text")
    assert texts.get("word_not_found") == "custom text"

    # persisted, not just cached: a fresh cache load from the DB sees it too
    await texts.init_cache(db)
    assert texts.get("word_not_found") == "custom text"

    reset_value = await texts.reset_text(db, "word_not_found")
    assert reset_value == default
    assert texts.get("word_not_found") == default


async def test_texts_set_rejects_unknown_placeholder(db):
    await texts.init_cache(db)
    with pytest.raises(ValueError, match="unknown placeholders"):
        await texts.set_text(db, "challenge_created", "{nope}")


async def test_texts_list_reports_override_state(db):
    await texts.init_cache(db)
    before = {t["key"]: t for t in texts.list_texts()}["word_not_found"]
    assert before["is_overridden"] is False

    await texts.set_text(db, "word_not_found", "custom")
    after = {t["key"]: t for t in texts.list_texts()}["word_not_found"]
    assert after["is_overridden"] is True
    assert after["value"] == "custom"


# --- admin API ---

@pytest_asyncio.fixture
async def admin_client(db):
    app.state.db = db
    await texts.init_cache(db)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def test_admin_api_requires_auth(admin_client):
    res = await admin_client.get("/admin/api/texts")
    assert res.status_code == 401


async def test_admin_api_rejects_non_admin_session(admin_client):
    token = sign_session(999)  # not in ADMIN_IDS
    admin_client.cookies.set(COOKIE_NAME, token)
    res = await admin_client.get("/admin/api/texts")
    assert res.status_code == 401


async def test_admin_auth_token_sets_session_cookie(admin_client):
    token = sign_login_token(42)
    res = await admin_client.get(
        f"/admin/auth/token?token={token}", follow_redirects=False
    )
    assert res.status_code in (302, 307)
    assert COOKIE_NAME in res.cookies

    admin_client.cookies.set(COOKIE_NAME, res.cookies[COOKIE_NAME])
    res = await admin_client.get("/admin/api/texts")
    assert res.status_code == 200


async def test_admin_auth_token_rejects_non_admin(admin_client):
    token = sign_login_token(999)  # not in ADMIN_IDS
    res = await admin_client.get(
        f"/admin/auth/token?token={token}", follow_redirects=False
    )
    assert res.status_code == 403


async def test_admin_api_texts_crud(admin_client):
    token = sign_session(42)  # ADMIN_IDS=42, set in conftest
    admin_client.cookies.set(COOKIE_NAME, token)

    res = await admin_client.get("/admin/api/texts")
    assert res.status_code == 200
    keys = {t["key"] for t in res.json()}
    assert "word_not_found" in keys

    res = await admin_client.put("/admin/api/texts/word_not_found", json={"value": "новый текст"})
    assert res.status_code == 200
    assert texts.get("word_not_found") == "новый текст"

    res = await admin_client.put("/admin/api/texts/nonexistent_key", json={"value": "x"})
    assert res.status_code == 404

    res = await admin_client.post("/admin/api/texts/word_not_found/reset")
    assert res.status_code == 200
    assert texts.get("word_not_found") == texts.DEFAULTS["word_not_found"]
