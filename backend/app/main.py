"""FastAPI + aiogram bot in one asyncio process (TECH_SPEC §1)."""

import asyncio
import contextlib
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI

from app.api import router
from app.bot.runner import run_bot
from app.config import get_settings
from app.db import Database
from app.services.lemmatize import load_en_forms

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    static = settings.static_db_path if Path(settings.static_db_path).exists() else None
    app.state.db = await Database.open(settings.db_path, static)
    en_forms_path = Path(settings.data_dir) / "en_forms.json"
    if en_forms_path.exists():
        load_en_forms(en_forms_path)

    bot_task: asyncio.Task | None = None
    if settings.run_bot and settings.bot_token != "test:token":
        bot_task = asyncio.create_task(run_bot(settings.bot_token, app.state.db))

    yield

    if bot_task:
        bot_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await bot_task
    await app.state.db.close()


app = FastAPI(title="Теплее!", lifespan=lifespan)
app.include_router(router)
