"""Long-polling bot runner sharing the FastAPI event loop (TECH_SPEC §1, §6)."""

import logging

from aiogram import Bot, Dispatcher

from app.bot.handlers import router
from app.db import Database

log = logging.getLogger(__name__)


def build_dispatcher(db: Database) -> Dispatcher:
    dp = Dispatcher()
    dp.include_router(router)
    # injected into handlers by aiogram's kwargs mechanism
    dp["db"] = db
    return dp


async def run_bot(bot: Bot, db: Database) -> None:
    """Caller owns the Bot instance (shared with the push scheduler) and its session."""
    dp = build_dispatcher(db)
    log.info("bot: starting long polling")
    await dp.start_polling(bot, handle_signals=False)
