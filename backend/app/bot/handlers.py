"""aiogram handlers: thin glue over app.services.game (TECH_SPEC §6)."""

import asyncio
import time

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

from app.admin_auth import admin_ids, sign_login_token
from app.bot import render
from app.config import get_settings
from app.db import Database
from app.services import challenge, game, texts, timing, vectors
from app.services.game import AlreadySolved, GuessResult, HintUnavailable, WordNotFound

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
        text = render.render_game_message(
            s["day_no"], lang, s["attempts"], last, s["solved"], s["hints_used"]
        )
        has_challenge_to_return_to = False
        last_challenge_id = user["last_challenge_id"]
        if last_challenge_id:
            meta = await challenge.get_meta(db, last_challenge_id)
            if meta is None:
                # Self-heal, same spirit as _resolve_game's stale-pointer handling:
                # don't leave a dead "back to challenge" button hanging around.
                await db.conn.execute(
                    "UPDATE users SET last_challenge_id = NULL WHERE telegram_id = ?", (user_id,)
                )
                await db.conn.commit()
            else:
                has_challenge_to_return_to = True
        keyboard = render.game_keyboard(has_challenge_to_return_to=has_challenge_to_return_to)
    else:
        creator = await game.get_user(db, challenge_meta["creator_id"])
        who = _display_name(creator)
        text = render.render_challenge_message(
            who, lang, s["attempts"], last, s["solved"], s["hints_used"]
        )
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

    if payload and payload.startswith("t_"):
        # Timing-game challenge deep link: Mini App only, no daily/game_message
        # state to touch — just hand over a WebApp button and stop.
        await game.ensure_user(
            db, message.from_user.id, message.from_user.username, message.from_user.first_name
        )
        challenge_id = payload.removeprefix("t_")
        meta = await timing.challenge_meta(db, challenge_id)
        if meta is None:
            await message.answer(texts.get("challenge_expired"))
        else:
            creator = await game.get_user(db, meta["creator_id"])
            await message.answer(
                render.timing_challenge_intro_text(_display_name(creator)),
                reply_markup=render.timing_challenge_keyboard(challenge_id),
            )
        return

    referred_by = payload if payload and payload.startswith("c_") else None
    await game.ensure_user(
        db,
        message.from_user.id,
        message.from_user.username,
        message.from_user.first_name,
        referred_by=referred_by,
    )
    # /start is the documented way out of the "write me the challenge word" state.
    await _set_awaiting_challenge(db, message.from_user.id, False)
    if referred_by:
        challenge_id = referred_by.removeprefix("c_")
        meta = await challenge.get_meta(db, challenge_id)
        if meta is None:
            await message.answer(texts.get("challenge_expired"))
        elif meta["creator_id"] == message.from_user.id:
            await message.answer(texts.get("challenge_own_link"))
        else:
            # last_challenge_id stores the bare id (not "c:"-prefixed), matching
            # the id challenge.get_meta() expects — active_game keeps the "c:"
            # prefix since it's a generic game_key shared with daily's "d:" form.
            await db.conn.execute(
                "UPDATE users SET active_game = ?, last_challenge_id = ? WHERE telegram_id = ?",
                (f"c:{challenge_id}", challenge_id, message.from_user.id),
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
    for key in ("onboarding_1", "onboarding_2"):
        await message.answer(texts.get(key))
    await update_game_message(bot, db, message.from_user.id, force_new=True)


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(texts.get("help"))


@router.message(Command("lang"))
async def cmd_lang(message: Message, db: Database, bot: Bot) -> None:
    user = await game.get_user(db, message.from_user.id)
    new_lang = "en" if user["lang_mode"] == "ru" else "ru"
    await game.set_lang(db, message.from_user.id, new_lang)
    flag = render.LANG_FLAG[new_lang]
    await message.answer(texts.get("lang_switched", flag=flag))
    await update_game_message(bot, db, message.from_user.id, force_new=True)


@router.message(Command("stats"))
async def cmd_stats(message: Message, db: Database) -> None:
    s = await game.stats(db, message.from_user.id)
    await message.answer(
        texts.get(
            "stats",
            wins=s["wins"],
            attempts_total=s["attempts_total"],
            streak=s["streak"],
            flag=render.LANG_FLAG[s["lang_mode"]],
        )
    )


@router.message(Command("admin"))
async def cmd_admin(message: Message) -> None:
    if message.from_user.id not in admin_ids():
        return  # silent: don't reveal the panel exists to non-admins
    settings = get_settings()
    token = sign_login_token(message.from_user.id)
    link = f"{settings.api_public_url}/admin/auth/token?token={token}"
    await message.answer(f"🔐 Вход в админку (ссылка на 5 минут):\n{link}")


@router.message(Command("mute"))
async def cmd_mute(message: Message, db: Database) -> None:
    await db.conn.execute(
        "UPDATE users SET notifications = 0 WHERE telegram_id = ?", (message.from_user.id,)
    )
    await db.conn.commit()
    await message.answer(texts.get("muted"))


@router.message(Command("unmute"))
async def cmd_unmute(message: Message, db: Database) -> None:
    await db.conn.execute(
        "UPDATE users SET notifications = 1 WHERE telegram_id = ?", (message.from_user.id,)
    )
    await db.conn.commit()
    await message.answer(texts.get("unmuted"))


async def _set_awaiting_challenge(db: Database, user_id: int, value: bool) -> None:
    """awaiting_challenge=1 makes the next plain message the challenge word."""
    await game.ensure_user(db, user_id)
    await db.conn.execute(
        "UPDATE users SET awaiting_challenge = ? WHERE telegram_id = ?", (int(value), user_id)
    )
    await db.conn.commit()


async def _create_challenge(bot: Bot, db: Database, message: Message, raw_word: str) -> None:
    """Rank raw_word into a challenge and reply with the invite link.

    All failures are reported by editing the "готовлю…" placeholder, so the chat
    keeps one message per attempt instead of a growing error trail.
    """
    user = await game.get_user(db, message.from_user.id)
    pending = await message.answer(texts.get("challenge_pending"))

    try:
        challenge_id = await challenge.create(
            db, get_settings().data_dir, message.from_user.id, user["lang_mode"], raw_word
        )
    except WordNotFound:
        # Stay armed: the user's next word is another attempt at the challenge,
        # not a guess in the daily game.
        await _set_awaiting_challenge(db, message.from_user.id, True)
        await bot.edit_message_text(
            texts.get("challenge_word_not_found"),
            chat_id=message.chat.id,
            message_id=pending.message_id,
        )
        return
    except vectors.VectorsUnavailable:
        await bot.edit_message_text(
            texts.get("challenge_unavailable"),
            chat_id=message.chat.id,
            message_id=pending.message_id,
        )
        return

    me = await bot.get_me()
    link = f"https://t.me/{me.username}?start=c_{challenge_id}"
    await bot.edit_message_text(
        render.challenge_created_text(link), chat_id=message.chat.id, message_id=pending.message_id
    )


@router.message(Command("challenge"))
@router.edited_message(Command("challenge"))
async def cmd_challenge(message: Message, db: Database, bot: Bot) -> None:
    args = (message.text or "").split(maxsplit=1)
    if len(args) < 2 or not args[1].strip():
        # Bare /challenge: ask for the word, same flow as the button.
        await _set_awaiting_challenge(db, message.from_user.id, True)
        await message.answer(texts.get("challenge_ask_word"))
        return

    await _set_awaiting_challenge(db, message.from_user.id, False)
    await _create_challenge(bot, db, message, args[1])


@router.callback_query(F.data == "back_to_daily")
async def cb_back_to_daily(callback: CallbackQuery, db: Database, bot: Bot) -> None:
    await db.conn.execute(
        "UPDATE users SET active_game = NULL WHERE telegram_id = ?", (callback.from_user.id,)
    )
    await db.conn.commit()
    await callback.answer()
    await update_game_message(bot, db, callback.from_user.id, force_new=True)


@router.callback_query(F.data == "back_to_challenge")
async def cb_back_to_challenge(callback: CallbackQuery, db: Database, bot: Bot) -> None:
    user = await game.get_user(db, callback.from_user.id)
    challenge_id = user["last_challenge_id"]
    meta = await challenge.get_meta(db, challenge_id) if challenge_id else None
    if meta is None:
        if challenge_id:  # clear the dead pointer
            await db.conn.execute(
                "UPDATE users SET last_challenge_id = NULL WHERE telegram_id = ?",
                (callback.from_user.id,),
            )
            await db.conn.commit()
        await callback.answer(texts.get("challenge_expired"), show_alert=True)
        return
    await db.conn.execute(
        "UPDATE users SET active_game = ? WHERE telegram_id = ?",
        (f"c:{challenge_id}", callback.from_user.id),
    )
    await db.conn.commit()
    await callback.answer()
    await update_game_message(bot, db, callback.from_user.id, force_new=True)


@router.callback_query(F.data.in_({"challenge_new", "reply_challenge"}))
async def cb_challenge_new(callback: CallbackQuery, db: Database, bot: Bot) -> None:
    await _set_awaiting_challenge(db, callback.from_user.id, True)
    await callback.answer()
    await bot.send_message(callback.from_user.id, texts.get("challenge_ask_word"))


@router.callback_query(F.data == "show_all")
async def cb_show_all(callback: CallbackQuery, db: Database, bot: Bot) -> None:
    user_id = callback.from_user.id
    user = await game.get_user(db, user_id)
    game_key, lang, _meta = await _resolve_game(db, user)
    s = await game.state(db, user_id, game_key, lang)
    await callback.answer()
    await bot.send_message(user_id, render.render_full_list(s["attempts"], lang, s["hints_used"]))


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
        share = render.share_text(
            s["day_no"], lang, s["attempts"], result.streak, result.hints_used, me.username
        )
        await bot.send_message(
            user_id,
            texts.get(
                "win_daily",
                word=result.word,
                attempts_count=result.attempts_count,
                hints_used=result.hints_used,
                streak=result.streak,
                share_text=share,
            ),
        )
        return

    challenge_id = game_key.removeprefix("c:")
    await challenge.record_win(db, challenge_id, user_id, result.attempts_count)
    await bot.send_message(
        user_id,
        texts.get(
            "win_challenge",
            word=result.word,
            attempts_count=result.attempts_count,
            hints_used=result.hints_used,
        ),
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
            texts.get("hint_no_attempts" if e.reason == "no_attempts" else "hint_solved"),
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
        key = "hint_no_attempts" if e.reason == "no_attempts" else "hint_solved"
        await message.answer(texts.get(key))


@router.message(F.text & ~F.text.startswith("/"))
@router.edited_message(F.text & ~F.text.startswith("/"))
async def on_guess(message: Message, db: Database, bot: Bot) -> None:
    user_id = message.from_user.id
    user = await game.get_user(db, user_id)

    # Armed by "Загадать другу"/bare /challenge: this message is the secret word.
    if user["awaiting_challenge"]:
        await _set_awaiting_challenge(db, user_id, False)
        await _create_challenge(bot, db, message, message.text)
        return

    game_key, lang, _meta = await _resolve_game(db, user)
    try:
        result = await game.guess(db, user_id, game_key, lang, message.text)
    except WordNotFound:
        err = await message.answer(texts.get("word_not_found"))
        asyncio.create_task(_delete_later(bot, message.chat.id, err.message_id))
        return
    except AlreadySolved:
        err = await message.answer(texts.get("already_solved"))
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
