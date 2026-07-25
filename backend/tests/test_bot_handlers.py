"""Regression tests for the game-message anchoring bug: a bot reply that
edits a message buried above other chat content is invisible to the user
even though it "worked" server-side. See update_game_message's force_new."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from aiogram.exceptions import TelegramForbiddenError

from app.bot import render
from app.bot.handlers import (
    cb_back_to_daily,
    cb_hint,
    cb_show_all,
    cmd_challenge,
    cmd_start,
    on_guess,
    update_game_message,
)
from app.services import challenge, game


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


def _fake_callback(user_id: int = 1) -> SimpleNamespace:
    return SimpleNamespace(
        from_user=SimpleNamespace(id=user_id, username="u", first_name="Test"),
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


async def test_on_guess_non_win_sends_new_game_message(db, monkeypatch):
    """Every guess response is a fresh message now, not an edit: live testing
    showed edited-in-place messages stayed pinned at an old position and
    were effectively invisible to the user."""
    monkeypatch.setattr(
        "app.bot.handlers.game.daily_game_key", lambda lang, day_id=None: f"d:0:{lang}"
    )
    await game.ensure_user(db, 1)
    await db.conn.execute("UPDATE users SET game_message_id = 111 WHERE telegram_id = 1")
    await db.conn.commit()

    bot = _fake_bot(next_message_id=222)
    message = _fake_message("деньги")  # rank 100 at day 0 ru, not a win

    await on_guess(message, db, bot)

    bot.edit_message_text.assert_not_called()
    bot.send_message.assert_awaited_once()
    message.answer.assert_not_called()
    assert (await game.get_user(db, 1))["game_message_id"] == 222


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

    # Win text now goes through bot.send_message (shared _handle_win helper,
    # same as the hint path), not message.answer.
    message.answer.assert_not_called()
    bot.edit_message_text.assert_not_called()
    assert bot.send_message.await_count == 2  # share text + fresh game message
    assert "Да!" in bot.send_message.await_args_list[0].args[1]
    assert (await game.get_user(db, 1))["game_message_id"] == 222


async def test_on_guess_word_not_found_keeps_user_message(db, monkeypatch):
    """The user's guess must survive in chat history — only the bot's own
    'word not found' reply gets auto-deleted (via _delete_later)."""
    monkeypatch.setattr(
        "app.bot.handlers.game.daily_game_key", lambda lang, day_id=None: f"d:0:{lang}"
    )
    await game.ensure_user(db, 1)

    bot = _fake_bot()
    message = _fake_message("несуществующееслово")

    await on_guess(message, db, bot)

    message.answer.assert_awaited_once()
    bot.delete_message.assert_not_called()


async def test_cb_show_all_sends_full_list_without_touching_game_message(db, monkeypatch):
    monkeypatch.setattr(
        "app.bot.handlers.game.daily_game_key", lambda lang, day_id=None: f"d:0:{lang}"
    )
    await game.ensure_user(db, 1)
    await db.conn.execute("UPDATE users SET game_message_id = 111 WHERE telegram_id = 1")
    await db.conn.commit()

    bot = _fake_bot()
    callback = _fake_callback()

    await cb_show_all(callback, db, bot)

    callback.answer.assert_awaited_once_with()
    bot.send_message.assert_awaited_once()
    assert "Все слова" in bot.send_message.await_args.args[1]
    bot.edit_message_text.assert_not_called()


async def test_cb_hint_reveals_word_and_sends_new_game_message(db, monkeypatch):
    monkeypatch.setattr(
        "app.bot.handlers.game.daily_game_key", lambda lang, day_id=None: f"d:0:{lang}"
    )
    await game.ensure_user(db, 1)
    await game.guess(db, 1, "d:0:ru", "ru", "кошка")  # best rank 2 -> hint reveals rank 1 "кот"

    bot = _fake_bot(next_message_id=222)
    callback = _fake_callback()

    await cb_hint(callback, db, bot)

    callback.answer.assert_awaited_once_with()
    bot.edit_message_text.assert_not_called()
    assert bot.send_message.await_count == 2  # share text + fresh game message
    game_msg = bot.send_message.await_args_list[-1].args[1]
    assert "кот" in game_msg and "1" in game_msg


async def test_cb_hint_no_attempts_shows_alert_without_touching_game_message(db, monkeypatch):
    monkeypatch.setattr(
        "app.bot.handlers.game.daily_game_key", lambda lang, day_id=None: f"d:0:{lang}"
    )
    await game.ensure_user(db, 1)

    bot = _fake_bot()
    callback = _fake_callback()

    await cb_hint(callback, db, bot)

    callback.answer.assert_awaited_once_with(render.HINT_NO_ATTEMPTS, show_alert=True)
    bot.send_message.assert_not_called()
    bot.edit_message_text.assert_not_called()


# --- challenges (Этап 5) ---


async def test_cmd_start_with_challenge_link_sets_active_game_and_sends_intro(db, fake_vectors):
    await game.ensure_user(db, 2, username="creator")
    challenge_id = await challenge.create(db, fake_vectors, 2, "ru", "кот")

    bot = _fake_bot()
    message = _fake_message(f"/start c_{challenge_id}", user_id=1)

    await cmd_start(message, db, bot)

    assert (await game.get_user(db, 1))["active_game"] == f"c:{challenge_id}"
    assert message.answer.await_count == 3  # intro + 2 onboarding parts
    intro = message.answer.await_args_list[0].args[0]
    assert "@creator" in intro


async def test_cmd_start_own_challenge_link_blocked(db, fake_vectors):
    challenge_id = await challenge.create(db, fake_vectors, 1, "ru", "кот")

    bot = _fake_bot()
    message = _fake_message(f"/start c_{challenge_id}", user_id=1)

    await cmd_start(message, db, bot)

    assert (await game.get_user(db, 1))["active_game"] is None
    assert message.answer.await_args_list[0].args[0] == render.CHALLENGE_OWN_LINK


async def test_cmd_start_expired_challenge_link(db):
    bot = _fake_bot()
    message = _fake_message("/start c_doesnotexist", user_id=1)

    await cmd_start(message, db, bot)

    assert (await game.get_user(db, 1))["active_game"] is None
    assert message.answer.await_args_list[0].args[0] == render.CHALLENGE_EXPIRED


async def test_cmd_start_bare_resets_active_game_to_daily(db):
    await game.ensure_user(db, 1)
    await db.conn.execute("UPDATE users SET active_game = 'c:whatever' WHERE telegram_id = 1")
    await db.conn.commit()

    bot = _fake_bot()
    message = _fake_message("/start", user_id=1)

    await cmd_start(message, db, bot)

    assert (await game.get_user(db, 1))["active_game"] is None


async def test_on_guess_routes_to_active_challenge(db, fake_vectors):
    await game.ensure_user(db, 2, username="creator")
    challenge_id = await challenge.create(db, fake_vectors, 2, "ru", "кот")
    await game.ensure_user(db, 1)
    await db.conn.execute(
        f"UPDATE users SET active_game = 'c:{challenge_id}' WHERE telegram_id = 1"
    )
    await db.conn.commit()

    bot = _fake_bot()
    message = _fake_message("собака", user_id=1)

    await on_guess(message, db, bot)

    cur = await db.conn.execute("SELECT game_key FROM attempts WHERE telegram_id = 1")
    rows = await cur.fetchall()
    assert [r["game_key"] for r in rows] == [f"c:{challenge_id}"]


async def test_stale_active_game_falls_back_to_daily(db, monkeypatch):
    monkeypatch.setattr(
        "app.bot.handlers.game.daily_game_key", lambda lang, day_id=None: f"d:0:{lang}"
    )
    await game.ensure_user(db, 1)
    await db.conn.execute("UPDATE users SET active_game = 'c:doesnotexist' WHERE telegram_id = 1")
    await db.conn.commit()

    bot = _fake_bot()
    message = _fake_message("кот", user_id=1)  # win at day 0 ru

    await on_guess(message, db, bot)

    assert (await game.get_user(db, 1))["active_game"] is None
    cur = await db.conn.execute("SELECT game_key FROM attempts WHERE telegram_id = 1")
    rows = await cur.fetchall()
    assert [r["game_key"] for r in rows] == ["d:0:ru"]


async def test_challenge_win_records_result_and_notifies_creator(db, fake_vectors):
    await game.ensure_user(db, 2, username="creator")
    challenge_id = await challenge.create(db, fake_vectors, 2, "ru", "кот")
    await game.ensure_user(db, 1, username="winner")
    await db.conn.execute(
        f"UPDATE users SET active_game = 'c:{challenge_id}' WHERE telegram_id = 1"
    )
    await db.conn.commit()

    bot = _fake_bot()
    message = _fake_message("кот", user_id=1)  # win

    await on_guess(message, db, bot)

    cur = await db.conn.execute(
        "SELECT * FROM challenge_results WHERE challenge_id = ? AND telegram_id = 1",
        (challenge_id,),
    )
    assert await cur.fetchone() is not None

    friend_calls = [c for c in bot.send_message.await_args_list if c.args[0] == 1]
    creator_calls = [c for c in bot.send_message.await_args_list if c.args[0] == 2]
    assert friend_calls  # win message (+ game message refresh)
    assert len(creator_calls) == 1
    assert "@winner" in creator_calls[0].args[1]


async def test_challenge_win_notify_swallows_forbidden(db, fake_vectors):
    await game.ensure_user(db, 2, username="creator")
    challenge_id = await challenge.create(db, fake_vectors, 2, "ru", "кот")
    await game.ensure_user(db, 1, username="winner")
    await db.conn.execute(
        f"UPDATE users SET active_game = 'c:{challenge_id}' WHERE telegram_id = 1"
    )
    await db.conn.commit()

    def side_effect(*a, **k):
        if a[0] == 2:
            raise TelegramForbiddenError(method=None, message="bot was blocked by the user")
        return Mock(message_id=999)

    bot = _fake_bot()
    bot.send_message.side_effect = side_effect
    message = _fake_message("кот", user_id=1)  # win

    await on_guess(message, db, bot)  # must not raise

    friend_calls = [c for c in bot.send_message.await_args_list if c.args[0] == 1]
    assert friend_calls  # friend still got their win message + game refresh


async def test_cb_back_to_daily_clears_active_game(db):
    await game.ensure_user(db, 1)
    await db.conn.execute("UPDATE users SET active_game = 'c:whatever' WHERE telegram_id = 1")
    await db.conn.commit()

    bot = _fake_bot()
    callback = _fake_callback(user_id=1)

    await cb_back_to_daily(callback, db, bot)

    callback.answer.assert_awaited_once_with()
    assert (await game.get_user(db, 1))["active_game"] is None


async def test_cmd_challenge_no_args_shows_usage(db):
    bot = _fake_bot()
    message = _fake_message("/challenge", user_id=1)

    await cmd_challenge(message, db, bot)

    message.answer.assert_awaited_once_with(render.CHALLENGE_USAGE)


async def test_cmd_challenge_success_edits_placeholder_to_link(db, fake_vectors, monkeypatch):
    monkeypatch.setattr(
        "app.bot.handlers.get_settings", lambda: SimpleNamespace(data_dir=fake_vectors)
    )
    bot = _fake_bot()
    message = _fake_message("/challenge кот", user_id=1)
    message.answer.return_value = Mock(message_id=99)

    await cmd_challenge(message, db, bot)

    bot.edit_message_text.assert_awaited_once()
    args, kwargs = bot.edit_message_text.await_args
    assert "t.me/teplee_bot?start=c_" in args[0]
    assert kwargs["chat_id"] == 1 and kwargs["message_id"] == 99


async def test_cmd_challenge_word_not_found(db, fake_vectors, monkeypatch):
    monkeypatch.setattr(
        "app.bot.handlers.get_settings", lambda: SimpleNamespace(data_dir=fake_vectors)
    )
    bot = _fake_bot()
    message = _fake_message("/challenge абракадабрище", user_id=1)
    message.answer.return_value = Mock(message_id=99)

    await cmd_challenge(message, db, bot)

    bot.edit_message_text.assert_awaited_once_with(
        render.CHALLENGE_WORD_NOT_FOUND, chat_id=1, message_id=99
    )


async def test_cmd_challenge_limit_enforced(db, fake_vectors, monkeypatch):
    monkeypatch.setattr(
        "app.bot.handlers.get_settings", lambda: SimpleNamespace(data_dir=fake_vectors)
    )
    for _ in range(challenge.MAX_ACTIVE):
        await challenge.create(db, fake_vectors, 1, "ru", "кот")

    bot = _fake_bot()
    message = _fake_message("/challenge кот", user_id=1)
    message.answer.return_value = Mock(message_id=5)

    await cmd_challenge(message, db, bot)

    bot.edit_message_text.assert_awaited_once_with(
        render.CHALLENGE_LIMIT, chat_id=1, message_id=5
    )
