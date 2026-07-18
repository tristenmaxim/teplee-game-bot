"""REST API for the Mini App (TECH_SPEC §4). Auth: 'Authorization: tma <initDataRaw>'."""

import time
from collections import defaultdict
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field

from app.auth import InvalidInitData, TelegramUser, validate_init_data
from app.config import get_settings
from app.db import Database
from app.services import game
from app.services.game import WordNotFound

router = APIRouter(prefix="/api")


# --- auth dependency ---

async def current_user(
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
) -> TelegramUser:
    if not authorization or not authorization.startswith("tma "):
        raise HTTPException(401, "missing tma authorization")
    settings = get_settings()
    try:
        user = validate_init_data(
            authorization.removeprefix("tma "),
            settings.bot_token,
            settings.init_data_max_age_s,
        )
    except InvalidInitData as e:
        raise HTTPException(401, str(e)) from e
    db: Database = request.app.state.db
    await game.ensure_user(db, user.id, user.username, user.first_name)
    return user


def get_db(request: Request) -> Database:
    return request.app.state.db


# --- rate limit: token bucket per user (in-memory, single process) ---

class TokenBucket:
    def __init__(self, rate: float, capacity: float | None = None):
        self.rate = rate
        self.capacity = capacity or rate
        self._state: dict[int, tuple[float, float]] = defaultdict(
            lambda: (self.capacity, time.monotonic())
        )

    def allow(self, key: int) -> bool:
        tokens, last = self._state[key]
        now = time.monotonic()
        tokens = min(self.capacity, tokens + (now - last) * self.rate)
        if tokens < 1:
            self._state[key] = (tokens, now)
            return False
        self._state[key] = (tokens - 1, now)
        return True


guess_bucket = TokenBucket(rate=get_settings().rate_limit_guess_per_s)


# --- helpers ---

async def resolve_game(
    db: Database, user_id: int, game_param: str, lang_override: str | None = None
) -> tuple[str, str]:
    """'d' | 'c_<id>' -> (game_key, lang)."""
    if game_param == "d":
        user = await game.get_user(db, user_id)
        lang = lang_override or user["lang_mode"]
        if lang not in ("ru", "en"):
            raise HTTPException(422, "bad lang")
        return game.daily_game_key(lang), lang
    if game_param.startswith("c_"):
        challenge_id = game_param.removeprefix("c_")
        cur = await db.conn.execute(
            "SELECT lang FROM challenges WHERE id = ? AND expires_at > datetime('now')",
            (challenge_id,),
        )
        row = await cur.fetchone()
        if row is None:
            raise HTTPException(404, "challenge not found or expired")
        return f"c:{challenge_id}", row["lang"]
    raise HTTPException(422, "bad game")


# --- schemas ---

class GuessIn(BaseModel):
    game: str = "d"
    word: str = Field(min_length=1, max_length=50)
    lang: Literal["ru", "en"] | None = None


class LangIn(BaseModel):
    lang: Literal["ru", "en"]


# --- endpoints ---

@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/state")
async def get_state(
    user: Annotated[TelegramUser, Depends(current_user)],
    db: Annotated[Database, Depends(get_db)],
    game_param: str = "d",
):
    game_key, lang = await resolve_game(db, user.id, game_param)
    return await game.state(db, user.id, game_key, lang)


@router.post("/guess")
async def post_guess(
    body: GuessIn,
    user: Annotated[TelegramUser, Depends(current_user)],
    db: Annotated[Database, Depends(get_db)],
):
    if not guess_bucket.allow(user.id):
        raise HTTPException(429, "slow down")
    game_key, lang = await resolve_game(db, user.id, body.game, body.lang)
    try:
        result = await game.guess(db, user.id, game_key, lang, body.word)
    except WordNotFound:
        raise HTTPException(409, "word_not_found") from None
    return {
        "word": result.word,
        "rank": result.rank,
        "is_new": result.is_new,
        "is_win": result.is_win,
        "attempts_count": result.attempts_count,
        "streak": result.streak,
    }


@router.post("/lang")
async def post_lang(
    body: LangIn,
    user: Annotated[TelegramUser, Depends(current_user)],
    db: Annotated[Database, Depends(get_db)],
):
    await game.set_lang(db, user.id, body.lang)
    return {"lang": body.lang}


@router.get("/stats")
async def get_stats(
    user: Annotated[TelegramUser, Depends(current_user)],
    db: Annotated[Database, Depends(get_db)],
):
    return await game.stats(db, user.id)
