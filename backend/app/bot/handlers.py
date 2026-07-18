"""aiogram handlers: thin glue over app.services.game (TECH_SPEC §6)."""

import asyncio
import time

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, Message

from app.bot import render
from app.config import get_settings
from app.db import Database
from app.services import game
from app.services.game import WordNotFound

router = Router()

# Telegram allows ~1 edit/sec per chat: per-user serialization + spacing.
_edit_locks: dict[int, asyncio.Lock] = {}
_last_edit: dict[int, float] = {}
EDIT_MIN_INTERVAL = 1.0


async def _delete_later(bot: Bot, chat_id: int, message_id: int, delay: float = 3.0) -> None:
    await asyncio.sleep(delay)
    try:
        await bot.delete_message(chat_id, message_id)
    except TelegramBadRequest:
        pass


async def _game_view(db: Database, user_id: int, last: dict | None = None) -> tuple[str, str]:
    user = await game.get_user(db, user_id)
    lang = user["lang_mode"]
    game_key = game.daily_game_key(lang)
    s = await game.state(db, user_id, game_key, lang)
    text = render.render_game_message(s["day_no"], lang, s["attempts"], last, s["solved"])
    return text, lang


async def update_game_message(
    bot: Bot, db: Database, user_id: int, last: dict | None = None
) -> None:
    """editMessageText of the single game message; resend if edit fails."""
    text, lang = await _game_view(db, user_id, last)
    keyboard = render.game_keyboard(get_settings().webapp_url, lang)
    user = await game.get_user(db, user_id)

    lock = _edit_locks.setdefault(user_id, asyncio.Lock())
    async with lock:
        wait = EDIT_MIN_INTERVAL - (time.monotonic() - _last_edit.get(user_id, 0.0))
        if wait > 0:
            await asyncio.sleep(wait)
        try:
            if user["game_message_id"] is None:
                raise TelegramBadRequest(method=None, message="no game message yet")
            await bot.edit_message_text(
                text, chat_id=user_id, message_id=user["game_message_id"], reply_markup=keyboard
            )
        except TelegramBadRequest as e:
            if "message is not modified" in str(e):
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
        # challenge deep links become playable in Этап 5
        await message.answer(render.CHALLENGE_SOON)
    for part in render.ONBOARDING:
        await message.answer(part)
    await update_game_message(bot, db, message.from_user.id)


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
    await update_game_message(bot, db, message.from_user.id)


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


@router.callback_query(F.data == "toggle_lang")
async def cb_toggle_lang(callback: CallbackQuery, db: Database, bot: Bot) -> None:
    user = await game.get_user(db, callback.from_user.id)
    new_lang = "en" if user["lang_mode"] == "ru" else "ru"
    await game.set_lang(db, callback.from_user.id, new_lang)
    await callback.answer(f"Теперь {render.LANG_FLAG[new_lang]}!")
    await update_game_message(bot, db, callback.from_user.id)


@router.callback_query(F.data == "challenge")
async def cb_challenge(callback: CallbackQuery) -> None:
    await callback.answer(render.CHALLENGE_SOON, show_alert=True)


@router.message(F.text & ~F.text.startswith("/"))
async def on_guess(message: Message, db: Database, bot: Bot) -> None:
    user_id = message.from_user.id
    user = await game.get_user(db, user_id)
    lang = user["lang_mode"]
    game_key = game.daily_game_key(lang)
    try:
        result = await game.guess(db, user_id, game_key, lang, message.text)
    except WordNotFound:
        err = await message.answer(render.WORD_NOT_FOUND)
        asyncio.create_task(_delete_later(bot, message.chat.id, err.message_id))
        return

    await update_game_message(
        bot, db, user_id, last={"word": result.word, "rank": result.rank}
    )

    if result.is_win and result.is_new:
        s = await game.state(db, user_id, game_key, lang)
        me = await bot.get_me()
        text = render.share_text(s["day_no"], lang, s["attempts"], result.streak, me.username)
        await message.answer(
            f"🎉 Да! Это «{result.word}» — ранг 1!\n"
            f"Попыток: {result.attempts_count} · Стрик: {result.streak}🔥\n\n"
            f"Поделись результатом:\n{text}"
        )
