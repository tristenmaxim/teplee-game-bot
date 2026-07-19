"""Regression tests for the game-message anchoring bug: a bot reply that
edits a message buried above other chat content is invisible to the user
even though it "worked" server-side. See update_game_message's force_new."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from app.bot.handlers import cmd_start, on_guess, update_game_message
from app.services import game


def _fake_bot(next_message_id: int = 100) -> AsyncMock:
    bot = AsyncMock()
    bot.send_message.side_effect = lambda *a, **k: Mock(message_id=next_message_id)
    bot.get_me = AsyncMock(return_value=Mock(username="teplee_bot"))
    return bot


def _fake_message(text: str, user_id: int = 1) -> SimpleNamespace:
    return SimpleNamespace(
        text=text,
        from_user=SimpleNamespace(id=user_id, username="u", first_name="Test"),
        chat=SimpleNamespace(id=user_id),
        answer=AsyncMock(),
    )


async def test_update_game_message_edits_in_place_by_default(db):
    await game.ensure_user(db, 1)
    await db.conn.execute("UPDATE users SET game_message_id = 999 WHERE telegram_id = 1")
    await db.conn.commit()

    bot = _fake_bot()
    await update_game_message(bot, db, 1)

    bot.edit_message_text.assert_awaited_once()
    bot.send_message.assert_not_called()


async def test_update_game_message_force_new_skips_edit(db):
    """Even with an existing game_message_id, force_new must send fresh and
    re-anchor — editing here would land on a message buried by prior chat
    content, which is exactly the bug a live user hit in production."""
    await game.ensure_user(db, 1)
    await db.conn.execute("UPDATE users SET game_message_id = 999 WHERE telegram_id = 1")
    await db.conn.commit()

    bot = _fake_bot(next_message_id=42)
    await update_game_message(bot, db, 1, force_new=True)

    bot.edit_message_text.assert_not_called()
    bot.send_message.assert_awaited_once()
    assert (await game.get_user(db, 1))["game_message_id"] == 42


async def test_cmd_start_reanchors_game_message_after_onboarding_text(db):
    """/start always sends onboarding text first; the game message that
    follows must be a fresh send, not an edit of whatever old message
    game_message_id still points at, or it ends up invisible below the
    onboarding text (the exact bug reported live)."""
    await game.ensure_user(db, 1)
    await db.conn.execute("UPDATE users SET game_message_id = 555 WHERE telegram_id = 1")
    await db.conn.commit()

    bot = _fake_bot(next_message_id=777)
    message = _fake_message("/start")

    await cmd_start(message, db, bot)

    assert message.answer.await_count == 2  # the two ONBOARDING parts
    bot.edit_message_text.assert_not_called()
    bot.send_message.assert_awaited_once()
    assert (await game.get_user(db, 1))["game_message_id"] == 777


async def test_on_guess_non_win_edits_in_place(db, monkeypatch):
    monkeypatch.setattr(
        "app.bot.handlers.game.daily_game_key", lambda lang, day_id=None: f"d:0:{lang}"
    )
    await game.ensure_user(db, 1)
    await db.conn.execute("UPDATE users SET game_message_id = 111 WHERE telegram_id = 1")
    await db.conn.commit()

    bot = _fake_bot()
    message = _fake_message("деньги")  # rank 100 at day 0 ru, not a win

    await on_guess(message, db, bot)

    bot.edit_message_text.assert_awaited_once()
    bot.send_message.assert_not_called()
    message.answer.assert_not_called()


async def test_on_guess_win_forces_new_game_message_after_share_text(db, monkeypatch):
    """Winning sends a share-text message; the game view must then be
    re-anchored below it (force_new), or post-win extra guesses would keep
    editing a message buried under the share text."""
    monkeypatch.setattr(
        "app.bot.handlers.game.daily_game_key", lambda lang, day_id=None: f"d:0:{lang}"
    )
    await game.ensure_user(db, 1)
    await db.conn.execute("UPDATE users SET game_message_id = 111 WHERE telegram_id = 1")
    await db.conn.commit()

    bot = _fake_bot(next_message_id=222)
    message = _fake_message("кот")  # rank 1 at day 0 ru == win

    await on_guess(message, db, bot)

    message.answer.assert_awaited_once()
    assert "Да!" in message.answer.await_args.args[0]
    bot.edit_message_text.assert_not_called()
    bot.send_message.assert_awaited_once()
    assert (await game.get_user(db, 1))["game_message_id"] == 222
