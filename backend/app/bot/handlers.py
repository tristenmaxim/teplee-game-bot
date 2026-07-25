"""aiogram handlers: thin glue over app.services.game (TECH_SPEC §6)."""

import asyncio
import time

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

from app.bot import render
from app.config import get_settings
from app.db import Database
from app.services import challenge, game, vectors
from app.services.game import GuessResult, HintUnavailable, WordNotFound

router = Router()

# Telegram allows ~1 edit/sec per chat: per-user serialization + spacing.
_edit_locks: dict[int, asyncio.Lock] = {}
_last_edit: dict[int, float] = {}
EDIT_MIN_INTERVAL = 1.0


def _display_name(user: dict) -> str:
    return f"@{user['username']}" if user["username"] else (user["first_name"] or "друг")


async def _delete_later(bot: Bot, chat_id: int, message_id: int, delay: float = 3.0) -> None:
    await asyncio.sleep(delay)
    try:
        await bot.delete_message(chat_id, message_id)
    except TelegramBadRequest:
        pass


async def _resolve_game(db: Database, user: dict) -> tuple[str, str, dict | None]:
    """(game_key, lang, challenge_meta). challenge_meta is None for daily play.

    Self-heals: if user['active_game'] points at an expired/deleted challenge,
    clears the column back to NULL and falls back to daily instead of erroring.
    """
    active = user["active_game"]
    if not active:
        return game.daily_game_key(user["lang_mode"]), user["lang_mode"], None

    meta = await challenge.get_meta(db, active.removeprefix("c:"))
    if meta is None:
        await db.conn.execute(
            "UPDATE users SET active_game = NULL WHERE telegram_id = ?", (user["telegram_id"],)
        )
        await db.conn.commit()
        return game.daily_game_key(user["lang_mode"]), user["lang_mode"], None

    return active, meta["lang"], meta


async def _game_view(
    db: Database, user_id: int, last: dict | None = None
) -> tuple[str, InlineKeyboardMarkup]:
    user = await game.get_user(db, user_id)
    game_key, lang, challenge_meta = await _resolve_game(db, user)
    s = await game.state(db, user_id, game_key, lang)

    if challenge_meta is None:
        text = render.render_game_message(s["day_no"], lang, s["attempts"], last, s["solved"])
        keyboard = render.game_keyboard()
    else:
        creator = await game.get_user(db, challenge_meta["creator_id"])
        who = _display_name(creator)
        text = render.render_challenge_message(who, lang, s["attempts"], last, s["solved"])
        keyboard = render.game_keyboard(in_challenge=True)
    return text, keyboard


async def update_game_message(
    bot: Bot, db: Database, user_id: int, last: dict | None = None, force_new: bool = False
) -> None:
    """editMessageText of the single game message; resend if edit fails.

    force_new: skip the edit and always send+re-anchor. Needed whenever other
    messages were just sent to this chat (onboarding, /lang confirmation) —
    otherwise the edit lands on a message now buried above that new text,
    invisible next to the input box (see the day-1 daily-push bug).
    """
    text, keyboard = await _game_view(db, user_id, last)
    user = await game.get_user(db, user_id)

    lock = _edit_locks.setdefault(user_id, asyncio.Lock())
    async with lock:
        wait = EDIT_MIN_INTERVAL - (time.monotonic() - _last_edit.get(user_id, 0.0))
        if wait > 0:
            await asyncio.sleep(wait)
        try:
            if force_new or user["game_message_id"] is None:
                raise TelegramBadRequest(method=None, message="new game message needed")
            await bot.edit_message_text(
                text, chat_id=user_id, message_id=user["game_message_id"], reply_markup=keyboard
            )
        except TelegramBadRequest as e:
            if not force_new and "message is not modified" in str(e):
                return
            msg = await bot.send_message(user_id, text, reply_markup=keyboard)
            await db.conn.execute(
                "UPDATE users SET game_message_id = ? WHERE telegram_id = ?",
                (msg.message_id, user_id),
            )
            await db.conn.commit()
        finally:
            _last_edit[user_id] = time.monotonic()


@router.message(CommandStart())
async def cmd_start(message: Message, db: Database, bot: Bot) -> None:
    args = (message.text or "").split(maxsplit=1)
    payload = args[1] if len(args) > 1 else None
    referred_by = payload if payload and payload.startswith("c_") else None
    await game.ensure_user(
        db,
        message.from_user.id,
        message.from_user.username,
        message.from_user.first_name,
        referred_by=referred_by,
    )
    if referred_by:
        challenge_id = referred_by.removeprefix("c_")
        meta = await challenge.get_meta(db, challenge_id)
        if meta is None:
            await message.answer(render.CHALLENGE_EXPIRED)
        elif meta["creator_id"] == message.from_user.id:
            await message.answer(render.CHALLENGE_OWN_LINK)
        else:
            await db.conn.execute(
                "UPDATE users SET active_game = ? WHERE telegram_id = ?",
                (f"c:{challenge_id}", message.from_user.id),
            )
            await db.conn.commit()
            creator = await game.get_user(db, meta["creator_id"])
            await message.answer(render.challenge_intro_text(_display_name(creator)))
    else:
        # Bare /start: explicit return-to-daily, in case active_game was set.
        await db.conn.execute(
            "UPDATE users SET active_game = NULL WHERE telegram_id = ?", (message.from_user.id,)
        )
        await db.conn.commit()
    for part in render.ONBOARDING:
        await message.answer(part)
    await update_game_message(bot, db, message.from_user.id, force_new=True)


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(render.HELP_TEXT)


@router.message(Command("lang"))
async def cmd_lang(message: Message, db: Database, bot: Bot) -> None:
    user = await game.get_user(db, message.from_user.id)
    new_lang = "en" if user["lang_mode"] == "ru" else "ru"
    await game.set_lang(db, message.from_user.id, new_lang)
    flag = render.LANG_FLAG[new_lang]
    await message.answer(f"Режим переключён: теперь угадываем {flag} слово!")
    await update_game_message(bot, db, message.from_user.id, force_new=True)


@router.message(Command("stats"))
async def cmd_stats(message: Message, db: Database) -> None:
    s = await game.stats(db, message.from_user.id)
    await message.answer(
        f"📊 Твоя статистика\n\n"
        f"Побед: {s['wins']} 🏆\nПопыток всего: {s['attempts_total']}\n"
        f"Стрик: {s['streak']}🔥\nЯзык: {render.LANG_FLAG[s['lang_mode']]}"
    )


@router.message(Command("mute"))
async def cmd_mute(message: Message, db: Database) -> None:
    await db.conn.execute(
        "UPDATE users SET notifications = 0 WHERE telegram_id = ?", (message.from_user.id,)
    )
    await db.conn.commit()
    await message.answer(render.MUTED)


@router.message(Command("unmute"))
async def cmd_unmute(message: Message, db: Database) -> None:
    await db.conn.execute(
        "UPDATE users SET notifications = 1 WHERE telegram_id = ?", (message.from_user.id,)
    )
    await db.conn.commit()
    await message.answer(render.UNMUTED)


@router.message(Command("challenge"))
async def cmd_challenge(message: Message, db: Database, bot: Bot) -> None:
    args = (message.text or "").split(maxsplit=1)
    if len(args) < 2 or not args[1].strip():
        await message.answer(render.CHALLENGE_USAGE)
        return

    user = await game.get_user(db, message.from_user.id)
    lang = user["lang_mode"]
    pending = await message.answer(render.CHALLENGE_PENDING)

    try:
        challenge_id = await challenge.create(
            db, get_settings().data_dir, message.from_user.id, lang, args[1]
        )
    except WordNotFound:
        await bot.edit_message_text(
            render.CHALLENGE_WORD_NOT_FOUND, chat_id=message.chat.id, message_id=pending.message_id
        )
        return
    except challenge.TooManyChallenges:
        await bot.edit_message_text(
            render.CHALLENGE_LIMIT, chat_id=message.chat.id, message_id=pending.message_id
        )
        return
    except vectors.VectorsUnavailable:
        await bot.edit_message_text(
            render.CHALLENGE_UNAVAILABLE, chat_id=message.chat.id, message_id=pending.message_id
        )
        return

    me = await bot.get_me()
    link = f"https://t.me/{me.username}?start=c_{challenge_id}"
    await bot.edit_message_text(
        render.challenge_created_text(link), chat_id=message.chat.id, message_id=pending.message_id
    )


@router.callback_query(F.data == "back_to_daily")
async def cb_back_to_daily(callback: CallbackQuery, db: Database, bot: Bot) -> None:
    await db.conn.execute(
        "UPDATE users SET active_game = NULL WHERE telegram_id = ?", (callback.from_user.id,)
    )
    await db.conn.commit()
    await callback.answer()
    await update_game_message(bot, db, callback.from_user.id, force_new=True)


@router.callback_query(F.data == "challenge_howto")
async def cb_challenge_howto(callback: CallbackQuery) -> None:
    await callback.answer(render.CHALLENGE_HOWTO, show_alert=True)


@router.callback_query(F.data == "reply_challenge")
async def cb_reply_challenge(callback: CallbackQuery, bot: Bot) -> None:
    await callback.answer()
    await bot.send_message(callback.from_user.id, render.CHALLENGE_USAGE)


@router.callback_query(F.data == "show_all")
async def cb_show_all(callback: CallbackQuery, db: Database, bot: Bot) -> None:
    user_id = callback.from_user.id
    user = await game.get_user(db, user_id)
    game_key, lang, _meta = await _resolve_game(db, user)
    s = await game.state(db, user_id, game_key, lang)
    await callback.answer()
    await bot.send_message(user_id, render.render_full_list(s["attempts"], lang))


async def _handle_win(
    bot: Bot, db: Database, user_id: int, lang: str, game_key: str, result: GuessResult
) -> None:
    """Send the win message appropriate to daily vs. challenge play.

    Challenge wins also record the result and best-effort notify the creator —
    a blocked/deleted creator chat must not break the winner's own flow.
    """
    if game_key.startswith("d:"):
        s = await game.state(db, user_id, game_key, lang)
        me = await bot.get_me()
        text = render.share_text(s["day_no"], lang, s["attempts"], result.streak, me.username)
        await bot.send_message(
            user_id,
            f"🎉 Да! Это «{result.word}» — ранг 1!\n"
            f"Попыток: {result.attempts_count} · Стрик: {result.streak}🔥\n\n"
            f"Поделись результатом:\n{text}",
        )
        return

    challenge_id = game_key.removeprefix("c:")
    await challenge.record_win(db, challenge_id, user_id, result.attempts_count)
    await bot.send_message(
        user_id,
        f"🎉 Да! Это «{result.word}» — ранг 1!\nПопыток: {result.attempts_count}",
        reply_markup=render.challenge_win_keyboard(),
    )

    meta = await challenge.get_meta(db, challenge_id)
    if meta is not None:
        winner = await game.get_user(db, user_id)
        text = render.creator_notify_text(_display_name(winner), result.attempts_count)
        try:
            await bot.send_message(meta["creator_id"], text)
        except (TelegramForbiddenError, TelegramBadRequest):
            pass


async def _deliver_hint(bot: Bot, db: Database, user_id: int, lang: str, game_key: str) -> None:
    """Call game.hint and, on success, send win message + refresh the game message.

    Raises HintUnavailable if no attempts left or already solved — caller handles it.
    """
    result = await game.hint(db, user_id, game_key, lang)

    is_win = result.is_win and result.is_new
    if is_win:
        await _handle_win(bot, db, user_id, lang, game_key, result)

    await update_game_message(
        bot, db, user_id, last={"word": result.word, "rank": result.rank}, force_new=True
    )


@router.callback_query(F.data == "hint")
async def cb_hint(callback: CallbackQuery, db: Database, bot: Bot) -> None:
    user_id = callback.from_user.id
    user = await game.get_user(db, user_id)
    game_key, lang, _meta = await _resolve_game(db, user)
    try:
        await _deliver_hint(bot, db, user_id, lang, game_key)
    except HintUnavailable as e:
        await callback.answer(
            render.HINT_NO_ATTEMPTS if e.reason == "no_attempts" else render.HINT_SOLVED,
            show_alert=True,
        )
        return

    await callback.answer()


@router.message(Command("hint"))
async def cmd_hint(message: Message, db: Database, bot: Bot) -> None:
    user_id = message.from_user.id
    user = await game.get_user(db, user_id)
    game_key, lang, _meta = await _resolve_game(db, user)
    try:
        await _deliver_hint(bot, db, user_id, lang, game_key)
    except HintUnavailable as e:
        text = render.HINT_NO_ATTEMPTS if e.reason == "no_attempts" else render.HINT_SOLVED
        await message.answer(text)


@router.message(F.text & ~F.text.startswith("/"))
async def on_guess(message: Message, db: Database, bot: Bot) -> None:
    user_id = message.from_user.id
    user = await game.get_user(db, user_id)
    game_key, lang, _meta = await _resolve_game(db, user)
    try:
        result = await game.guess(db, user_id, game_key, lang, message.text)
    except WordNotFound:
        err = await message.answer(render.WORD_NOT_FOUND)
        asyncio.create_task(_delete_later(bot, message.chat.id, err.message_id))
        return

    is_win = result.is_win and result.is_new
    if is_win:
        await _handle_win(bot, db, user_id, lang, game_key, result)

    # Always send a fresh game message rather than editing in place: live
    # testing showed editing left the game view buried at its old position,
    # invisible next to the input box.
    await update_game_message(
        bot, db, user_id, last={"word": result.word, "rank": result.rank}, force_new=True
    )
