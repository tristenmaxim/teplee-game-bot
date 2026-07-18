"""FastAPI app entrypoint. The aiogram bot joins this event loop in Этап 3."""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI

from app.api import router
from app.config import get_settings
from app.db import Database
from app.services.lemmatize import load_en_forms


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    static = settings.static_db_path if Path(settings.static_db_path).exists() else None
    app.state.db = await Database.open(settings.db_path, static)
    en_forms_path = Path(settings.data_dir) / "en_forms.json"
    if en_forms_path.exists():
        load_en_forms(en_forms_path)
    yield
    await app.state.db.close()


app = FastAPI(title="Теплее!", lifespan=lifespan)
app.include_router(router)
