from unittest.mock import AsyncMock, Mock

import pytest
from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter

from app.bot.push import _push_text, send_daily_push
from app.services import game


def _bot_with_message_ids(start: int = 100) -> AsyncMock:
    bot = AsyncMock()
    counter = iter(range(start, start + 1000))
    bot.send_message.side_effect = lambda *a, **k: Mock(message_id=next(counter))
    return bot


def test_push_text_with_yesterday():
    text = _push_text(43, "ru", "молоко")
    assert text == "🌅 Слово дня #43 🇷🇺 уже ждёт! Вчера было: МОЛОКО"


def test_push_text_no_yesterday():
    text = _push_text(0, "en", None)
    assert text == "🌅 Слово дня #0 🇬🇧 уже ждёт!"


async def test_send_daily_push_happy_path(db):
    await game.ensure_user(db, 1)
    await game.ensure_user(db, 2)
    await game.set_lang(db, 2, "en")

    bot = _bot_with_message_ids()
    await send_daily_push(bot, db)

    assert bot.send_message.await_count == 2
    sent_ids = {call.args[0] for call in bot.send_message.await_args_list}
    assert sent_ids == {1, 2}

    assert (await game.get_user(db, 1))["game_message_id"] is not None
    assert (await game.get_user(db, 2))["game_message_id"] is not None

async def test_send_daily_push_respects_mute(db):
    await game.ensure_user(db, 1)
    await db.conn.execute("UPDATE users SET notifications = 0 WHERE telegram_id = 1")
    await db.conn.commit()

    bot = AsyncMock()
    await send_daily_push(bot, db)
    bot.send_message.assert_not_called()


async def test_send_daily_push_forbidden_mutes_user(db):
    await game.ensure_user(db, 1)
    bot = AsyncMock()
    bot.send_message.side_effect = TelegramForbiddenError(method=None, message="blocked")

    await send_daily_push(bot, db)

    user = await game.get_user(db, 1)
    assert user["notifications"] == 0


async def test_send_daily_push_retries_after_flood_wait(db):
    await game.ensure_user(db, 1)
    bot = AsyncMock()
    bot.send_message.side_effect = [
        TelegramRetryAfter(method=None, message="flood", retry_after=0),
        Mock(message_id=101),
    ]

    await send_daily_push(bot, db)

    assert bot.send_message.await_count == 2


async def test_send_daily_push_yesterday_word_by_lang(db):
    await game.ensure_user(db, 1)  # ru
    await game.ensure_user(db, 2)
    await game.set_lang(db, 2, "en")

    bot = _bot_with_message_ids()
    await send_daily_push(bot, db)

    texts = {call.args[0]: call.args[1] for call in bot.send_message.await_args_list}
    assert "кот" in texts[1].upper() or "КОТ" in texts[1]
    assert "CAT" in texts[2]


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    async def instant_sleep(_):
        return None

    monkeypatch.setattr("app.bot.push.asyncio.sleep", instant_sleep)


@pytest.fixture(autouse=True)
def _fixed_day(monkeypatch):
    """conftest's static db only has daily_words for day_id 0/1 — pin 'today' to 1
    so 'yesterday' (day 0: кот/cat) is deterministic instead of wall-clock-dependent."""
    monkeypatch.setattr("app.bot.push.clock.current_day_id", lambda: 1)
