"""FastAPI + aiogram bot in one asyncio process (TECH_SPEC §1)."""

import asyncio
import contextlib
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.admin_api import router as admin_router
from app.api import router
from app.bot.push import send_daily_push
from app.bot.runner import run_bot
from app.config import get_settings
from app.db import Database
from app.services import texts
from app.services.clock import MSK
from app.services.lemmatize import load_en_forms

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    static = settings.static_db_path if Path(settings.static_db_path).exists() else None
    app.state.db = await Database.open(settings.db_path, static)
    await texts.init_cache(app.state.db)
    en_forms_path = Path(settings.data_dir) / "en_forms.json"
    if en_forms_path.exists():
        load_en_forms(en_forms_path)

    bot_task: asyncio.Task | None = None
    scheduler: AsyncIOScheduler | None = None
    bot: Bot | None = None
    app.state.bot = None  # set below when the bot actually runs; admin_api checks this
    if settings.run_bot and settings.bot_token != "test:token":
        bot = Bot(token=settings.bot_token)
        app.state.bot = bot
        bot_task = asyncio.create_task(run_bot(bot, app.state.db))

        scheduler = AsyncIOScheduler(timezone=MSK)
        scheduler.add_job(
            send_daily_push,
            CronTrigger(hour=9, minute=0, timezone=MSK),
            args=[bot, app.state.db],
            id="daily_push",
        )
        scheduler.start()

    yield

    if scheduler:
        scheduler.shutdown(wait=False)
    if bot_task:
        bot_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await bot_task
    if bot:
        await bot.session.close()
    await app.state.db.close()


app = FastAPI(title="Теплее!", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[get_settings().webapp_url],
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type"],
)
app.include_router(router)
app.include_router(admin_router)
