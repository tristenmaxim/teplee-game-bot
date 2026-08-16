from unittest.mock import AsyncMock, Mock

import pytest
import pytest_asyncio
from aiogram.exceptions import TelegramForbiddenError
from httpx import ASGITransport, AsyncClient

from app.admin_auth import (
    COOKIE_NAME,
    InvalidLogin,
    sign_login_token,
    sign_session,
    verify_login_token,
    verify_session,
)
from app.bot.broadcast import send_broadcast
from app.main import app
from app.services import admin as admin_stats
from app.services import game, texts

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


# --- admin dashboard / user search / upcoming words ---

async def test_dashboard_metrics_counts_day0_activity(db):
    await game.guess(db, 1, "d:0:ru", "ru", "кот")  # rank 1 -> win
    await game.guess(db, 2, "d:0:ru", "ru", "деньги")  # rank 100, not a win
    await db.conn.execute("UPDATE users SET notifications = 0 WHERE telegram_id = 2")
    await db.conn.commit()

    m = await admin_stats.dashboard_metrics(db, day_id=0)

    assert m["total_users"] == 2
    assert m["active_today"] == 2
    assert m["solved_today"] == 1
    assert m["avg_attempts_today"] == 1.0
    assert m["win_share_today"] == 0.5
    assert m["median_attempts_to_win"] == 1
    assert m["muted_users"] == 1
    assert any(u["telegram_id"] == 1 and u["streak"] == 1 for u in m["streak_leaders"])


async def test_dashboard_metrics_median_attempts_to_win(db):
    # user 1 wins in 2 tries, user 2 wins in 4 tries -> median 3
    await game.guess(db, 1, "d:0:ru", "ru", "деньги")  # rank 100
    await game.guess(db, 1, "d:0:ru", "ru", "кот")  # win, 2 tries
    await game.guess(db, 2, "d:0:ru", "ru", "собака")
    await game.guess(db, 2, "d:0:ru", "ru", "пар")
    await game.guess(db, 2, "d:0:ru", "ru", "деньги")
    await game.guess(db, 2, "d:0:ru", "ru", "кот")  # win, 4 tries

    m = await admin_stats.dashboard_metrics(db, day_id=0)

    assert m["median_attempts_to_win"] == 3


async def _seed_attempt(db, telegram_id: int, game_key: str, word: str, rank: int) -> None:
    await game.ensure_user(db, telegram_id)
    await db.conn.execute(
        "INSERT INTO attempts (telegram_id, game_key, word, rank) VALUES (?, ?, ?, ?)",
        (telegram_id, game_key, word, rank),
    )
    await db.conn.commit()


async def test_dashboard_metrics_retention(db):
    # telegram_id 1: first daily play on day 0, returns on day 1 and day 7 -> D1, D7 retained
    await _seed_attempt(db, 1, "d:0:ru", "деньги", 100)
    await _seed_attempt(db, 1, "d:1:ru", "деньги", 100)
    await _seed_attempt(db, 1, "d:7:ru", "деньги", 100)
    # telegram_id 2: first daily play on day 0, never returns -> not retained
    await _seed_attempt(db, 2, "d:0:ru", "деньги", 100)

    d1 = (await admin_stats.dashboard_metrics(db, day_id=1))["retention_d1"]
    d7 = (await admin_stats.dashboard_metrics(db, day_id=7))["retention_d7"]
    d30 = (await admin_stats.dashboard_metrics(db, day_id=30))["retention_d30"]

    assert d1 == {"cohort": 2, "retained": 1, "rate": 0.5}
    assert d7 == {"cohort": 2, "retained": 1, "rate": 0.5}
    assert d30 == {"cohort": 2, "retained": 0, "rate": 0.0}


async def test_search_users_by_id_and_username(db):
    await game.ensure_user(db, 777, username="tester", first_name="Tess")

    by_id = await admin_stats.search_users(db, "777")
    assert len(by_id) == 1
    assert by_id[0]["telegram_id"] == 777

    by_username = await admin_stats.search_users(db, "test")
    assert any(u["telegram_id"] == 777 for u in by_username)

    assert await admin_stats.search_users(db, "") == []
    assert await admin_stats.search_users(db, "nobody-like-this") == []


async def test_search_users_reports_attempts_and_wins(db):
    await game.guess(db, 5, "d:0:ru", "ru", "кошка")
    await game.guess(db, 5, "d:0:ru", "ru", "кот")  # win

    users = await admin_stats.search_users(db, "5")
    assert users[0]["attempts_total"] == 2
    assert users[0]["wins"] == 1


async def test_upcoming_words_reveals_answers_with_dates(db):
    from app.services import clock

    words = await admin_stats.upcoming_words(db, days=2, day_id=0)

    assert {(w["day_id"], w["lang"], w["word"]) for w in words} == {
        (0, "ru", "кот"),
        (0, "en", "cat"),
        (1, "ru", "собака"),
    }
    day0 = next(w for w in words if w["day_id"] == 0 and w["lang"] == "ru")
    assert day0["date"] == clock.EPOCH_DATE.isoformat()


# --- broadcast ---

def _fake_bot() -> AsyncMock:
    bot = AsyncMock()
    bot.send_message = AsyncMock()
    return bot


async def test_send_broadcast_reaches_all_users(db):
    await game.ensure_user(db, 1)
    await game.ensure_user(db, 2)
    bot = _fake_bot()

    result = await send_broadcast(bot, db, "hello")

    assert result == {"sent": 2, "forbidden": 0, "total": 2}
    assert bot.send_message.await_count == 2


async def test_send_broadcast_skips_guests(db):
    await game.ensure_user(db, 1)
    await game.ensure_user(db, -123456789012345, None, "Гость")
    bot = _fake_bot()

    result = await send_broadcast(bot, db, "hello")

    assert result == {"sent": 1, "forbidden": 0, "total": 1}
    assert bot.send_message.await_count == 1


async def test_send_broadcast_mutes_forbidden_users(db):
    await game.ensure_user(db, 1)
    await game.ensure_user(db, 2)
    bot = _fake_bot()
    bot.send_message.side_effect = [None, TelegramForbiddenError(method=None, message="blocked")]

    result = await send_broadcast(bot, db, "hello")

    assert result["sent"] == 1
    assert result["forbidden"] == 1
    assert (await game.get_user(db, 2))["notifications"] == 0


# --- admin API ---

@pytest_asyncio.fixture
async def admin_client(db):
    app.state.db = db
    app.state.bot = None
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


async def test_admin_api_dashboard_and_words_and_users(admin_client, db):
    await game.ensure_user(db, 42, username="owner")
    admin_client.cookies.set(COOKIE_NAME, sign_session(42))

    res = await admin_client.get("/admin/api/dashboard")
    assert res.status_code == 200
    assert res.json()["total_users"] == 1

    res = await admin_client.get("/admin/api/words")
    assert res.status_code == 200
    assert isinstance(res.json(), list)

    res = await admin_client.get("/admin/api/users?q=owner")
    assert res.status_code == 200
    assert res.json()[0]["telegram_id"] == 42


async def test_admin_api_broadcast_without_bot_is_503(admin_client):
    admin_client.cookies.set(COOKIE_NAME, sign_session(42))
    res = await admin_client.post("/admin/api/broadcast", json={"text": "hi"})
    assert res.status_code == 503


async def test_admin_api_broadcast_with_bot(admin_client, db):
    await game.ensure_user(db, 1)
    app.state.bot = Mock(send_message=AsyncMock())
    admin_client.cookies.set(COOKIE_NAME, sign_session(42))

    res = await admin_client.post("/admin/api/broadcast", json={"text": "hi all"})

    assert res.status_code == 200
    assert res.json()["sent"] == 1
    app.state.bot = None
