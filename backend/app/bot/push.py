"""Daily retention push at 09:00 MSK (TECH_SPEC.md §8).

Chunked to stay under Telegram's ~25 msg/sec, tolerant of blocked/kicked
users (Forbidden -> mute them) and flood control (RetryAfter -> back off).
"""

import asyncio
import logging

from aiogram import Bot
from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter

from app.db import Database
from app.services import clock

log = logging.getLogger(__name__)

CHUNK_SIZE = 25
CHUNK_INTERVAL_S = 1.0
LANG_FLAG = {"ru": "🇷🇺", "en": "🇬🇧"}


async def _yesterdays_words(db: Database, day_id: int) -> dict[str, str]:
    cur = await db.conn.execute(
        "SELECT lang, word FROM static.daily_words WHERE day_id = ?", (day_id - 1,)
    )
    return {row["lang"]: row["word"] for row in await cur.fetchall()}


def _push_text(day_no: int, lang: str, yesterday_word: str | None) -> str:
    text = f"🌅 Слово дня #{day_no} {LANG_FLAG[lang]} уже ждёт!"
    if yesterday_word:
        text += f" Вчера было: {yesterday_word.upper()}"
    return text


async def send_daily_push(bot: Bot, db: Database) -> None:
    day_id = clock.current_day_id()
    yesterday = await _yesterdays_words(db, day_id)

    cur = await db.conn.execute(
        "SELECT telegram_id, lang_mode FROM users WHERE notifications = 1"
    )
    rows = await cur.fetchall()
    log.info("daily push: sending to %d users", len(rows))

    sent = forbidden = 0
    for i, row in enumerate(rows):
        text = _push_text(day_id, row["lang_mode"], yesterday.get(row["lang_mode"]))
        try:
            await bot.send_message(row["telegram_id"], text)
            sent += 1
        except TelegramRetryAfter as e:
            await asyncio.sleep(e.retry_after)
            try:
                await bot.send_message(row["telegram_id"], text)
                sent += 1
            except (TelegramForbiddenError, TelegramRetryAfter):
                pass
        except TelegramForbiddenError:
            forbidden += 1
            await db.conn.execute(
                "UPDATE users SET notifications = 0 WHERE telegram_id = ?",
                (row["telegram_id"],),
            )
        if (i + 1) % CHUNK_SIZE == 0:
            await db.conn.commit()
            await asyncio.sleep(CHUNK_INTERVAL_S)

    await db.conn.commit()
    log.info("daily push: done, sent=%d forbidden=%d", sent, forbidden)
