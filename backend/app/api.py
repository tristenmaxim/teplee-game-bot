"""REST API for the Mini App (TECH_SPEC §4). Auth: 'Authorization: tma <initDataRaw>'."""

import json
import random
import time
from collections import defaultdict
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field

from app.auth import (
    InvalidInitData,
    TelegramUser,
    sign_init_data,
    validate_init_data,
    validate_login_widget,
)
from app.config import get_settings
from app.db import Database
from app.services import challenge, game, timing, vectors, wordle
from app.services.game import AlreadySolved, HintUnavailable, WordNotFound

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


class HintIn(BaseModel):
    game: str = "d"
    lang: Literal["ru", "en"] | None = None


class LangIn(BaseModel):
    lang: Literal["ru", "en"]


class LoginWidgetIn(BaseModel):
    id: int
    first_name: str
    last_name: str | None = None
    username: str | None = None
    photo_url: str | None = None
    auth_date: int
    hash: str


class ChallengeIn(BaseModel):
    word: str = Field(min_length=1, max_length=50)


class WordleGuessIn(BaseModel):
    word: str = Field(min_length=1, max_length=10)


class TimingStartIn(BaseModel):
    mode: Literal["visible", "hidden"] = "visible"
    challenge: str | None = None


class TimingStopIn(BaseModel):
    round_id: str = Field(min_length=1, max_length=64)


class TimingChallengeIn(BaseModel):
    mode: Literal["visible", "hidden"] = "visible"


# --- endpoints ---

@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


def _mint_session(user_id: int, username: str | None, first_name: str | None) -> str:
    """Build a Mini-App-shaped session token so current_user() needs no
    separate code path for web logins/guests vs real Telegram initData."""
    return sign_init_data(
        {
            "auth_date": str(int(time.time())),
            "user": json.dumps(
                {"id": user_id, "username": username, "first_name": first_name},
                separators=(",", ":"),
            ),
        },
        get_settings().bot_token,
    )


@router.post("/auth/login")
async def post_auth_login(
    body: LoginWidgetIn,
    db: Annotated[Database, Depends(get_db)],
):
    """Telegram Login Widget → a Mini-App-style session token (TECH_SPEC §4 extension).

    Lets the game be opened in a plain browser, outside any Telegram client,
    while staying the same telegram_id-keyed account as the bot/Mini App.
    """
    data = {k: str(v) for k, v in body.model_dump(exclude_none=True).items()}
    try:
        user = validate_login_widget(data, get_settings().bot_token)
    except InvalidInitData as e:
        raise HTTPException(401, str(e)) from e

    await game.ensure_user(db, user.id, user.username, user.first_name)
    return {"init_data": _mint_session(user.id, user.username, user.first_name)}


@router.post("/auth/guest")
async def post_auth_guest(db: Annotated[Database, Depends(get_db)]):
    """No-Telegram-account entry point: a locally-persisted guest identity.

    Negative telegram_id — real Telegram user ids are always positive, so
    this is enough to keep guests out of bot-facing paths (daily push,
    broadcast) that would otherwise try to message a chat that never
    existed. Guests can't play challenges/share via the bot, only solo.
    """
    for _ in range(5):
        guest_id = -random.randint(10**14, 10**15 - 1)
        cur = await db.conn.execute("SELECT 1 FROM users WHERE telegram_id = ?", (guest_id,))
        if await cur.fetchone() is None:
            break
    else:
        raise HTTPException(503, "could not allocate guest id")  # pragma: no cover

    await game.ensure_user(db, guest_id, None, "Гость")
    return {"init_data": _mint_session(guest_id, None, "Гость")}


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
    except AlreadySolved:
        raise HTTPException(409, "solved") from None
    return {
        "word": result.word,
        "rank": result.rank,
        "is_new": result.is_new,
        "is_win": result.is_win,
        "attempts_count": result.attempts_count,
        "streak": result.streak,
        "hints_used": result.hints_used,
    }


@router.post("/hint")
async def post_hint(
    body: HintIn,
    user: Annotated[TelegramUser, Depends(current_user)],
    db: Annotated[Database, Depends(get_db)],
):
    game_key, lang = await resolve_game(db, user.id, body.game, body.lang)
    try:
        result = await game.hint(db, user.id, game_key, lang)
    except HintUnavailable as e:
        raise HTTPException(409, e.reason) from None
    return {
        "word": result.word,
        "rank": result.rank,
        "is_new": result.is_new,
        "is_win": result.is_win,
        "attempts_count": result.attempts_count,
        "streak": result.streak,
        "hints_used": result.hints_used,
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


@router.post("/challenge")
async def post_challenge(
    body: ChallengeIn,
    user: Annotated[TelegramUser, Depends(current_user)],
    db: Annotated[Database, Depends(get_db)],
):
    settings = get_settings()
    game_user = await game.get_user(db, user.id)
    try:
        challenge_id = await challenge.create(
            db, settings.data_dir, user.id, game_user["lang_mode"], body.word
        )
    except WordNotFound:
        raise HTTPException(409, "word_not_found") from None
    except vectors.VectorsUnavailable:
        raise HTTPException(503, "challenges_unavailable") from None
    return {
        "id": challenge_id,
        "link": f"https://t.me/{settings.bot_username}?start=c_{challenge_id}",
    }


@router.get("/wordle/state")
async def get_wordle_state(
    user: Annotated[TelegramUser, Depends(current_user)],
    db: Annotated[Database, Depends(get_db)],
):
    return await wordle.state(db, user.id, wordle.daily_game_key())


@router.post("/wordle/guess")
async def post_wordle_guess(
    body: WordleGuessIn,
    user: Annotated[TelegramUser, Depends(current_user)],
    db: Annotated[Database, Depends(get_db)],
):
    if not guess_bucket.allow(user.id):
        raise HTTPException(429, "slow down")
    try:
        result = await wordle.guess(db, user.id, wordle.daily_game_key(), body.word)
    except wordle.InvalidGuess:
        raise HTTPException(409, "word_not_found") from None
    except wordle.GameOver:
        raise HTTPException(409, "game_over") from None
    return {
        "attempts": [{"word": a.word, "feedback": a.feedback} for a in result.attempts],
        "solved": result.solved,
        "game_over": result.game_over,
        "streak": result.streak,
    }


@router.post("/timing/start")
async def post_timing_start(
    body: TimingStartIn,
    user: Annotated[TelegramUser, Depends(current_user)],
    db: Annotated[Database, Depends(get_db)],
):
    try:
        return await timing.start_round(db, user.id, body.mode, body.challenge)
    except timing.ChallengeNotFound:
        raise HTTPException(404, "challenge not found or expired") from None
    except timing.AlreadyPlayed:
        raise HTTPException(409, "already_played") from None


@router.post("/timing/stop")
async def post_timing_stop(
    body: TimingStopIn,
    user: Annotated[TelegramUser, Depends(current_user)],
    db: Annotated[Database, Depends(get_db)],
):
    try:
        return await timing.stop_round(db, user.id, body.round_id)
    except timing.RoundNotFound:
        raise HTTPException(404, "round_not_found") from None


@router.post("/timing/challenge")
async def post_timing_challenge(
    body: TimingChallengeIn,
    user: Annotated[TelegramUser, Depends(current_user)],
    db: Annotated[Database, Depends(get_db)],
):
    settings = get_settings()
    challenge_id = await timing.create_challenge(db, user.id, body.mode)
    return {
        "id": challenge_id,
        "mode": body.mode,
        "link": f"https://t.me/{settings.bot_username}?start=t_{challenge_id}",
    }


@router.get("/timing/challenge/{challenge_id}")
async def get_timing_challenge(
    challenge_id: str,
    _user: Annotated[TelegramUser, Depends(current_user)],
    db: Annotated[Database, Depends(get_db)],
):
    meta = await timing.challenge_meta(db, challenge_id)
    if meta is None:
        raise HTTPException(404, "challenge not found or expired")
    results = await timing.challenge_results(db, challenge_id)
    return {"mode": meta["mode"], "results": results}
