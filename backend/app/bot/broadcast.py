"""Admin-triggered broadcast to every user (see app/admin_api.py).

Same chunked-send/backoff shape as push.py's daily job, minus the
notifications=1 filter — a broadcast is an explicit announcement, not the
daily nudge, so it isn't gated by that opt-out.
"""

import asyncio
import logging

from aiogram import Bot
from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter

from app.db import Database

log = logging.getLogger(__name__)

CHUNK_SIZE = 25
CHUNK_INTERVAL_S = 1.0


async def send_broadcast(bot: Bot, db: Database, text: str) -> dict:
    # telegram_id > 0: excludes web guests (negative ids, see api.py's
    # post_auth_guest) — there's no real chat to broadcast into.
    cur = await db.conn.execute("SELECT telegram_id FROM users WHERE telegram_id > 0")
    rows = await cur.fetchall()

    sent = forbidden = 0
    for i, row in enumerate(rows):
        telegram_id = row["telegram_id"]
        try:
            await bot.send_message(telegram_id, text)
            sent += 1
        except TelegramRetryAfter as e:
            await asyncio.sleep(e.retry_after)
            try:
                await bot.send_message(telegram_id, text)
                sent += 1
            except (TelegramForbiddenError, TelegramRetryAfter):
                pass
        except TelegramForbiddenError:
            forbidden += 1
            await db.conn.execute(
                "UPDATE users SET notifications = 0 WHERE telegram_id = ?", (telegram_id,)
            )
        if (i + 1) % CHUNK_SIZE == 0:
            await db.conn.commit()
            await asyncio.sleep(CHUNK_INTERVAL_S)

    await db.conn.commit()
    log.info("broadcast: done, sent=%d forbidden=%d", sent, forbidden)
    return {"sent": sent, "forbidden": forbidden, "total": len(rows)}
