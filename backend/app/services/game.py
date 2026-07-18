"""Game engine shared by bot and API — no HTTP layer in between (CLAUDE.md).

game_key: 'd:<day_id>:<lang>' (daily) | 'c:<challenge_id>' (challenge).
Rank 1 = win. Repeating a word is not an error (is_new=False, same rank).
"""

from dataclasses import dataclass

from app.db import Database
from app.services import clock
from app.services.lemmatize import lookup_candidates


class WordNotFound(Exception):
    """The guess is not in the game dictionary."""


@dataclass
class GuessResult:
    word: str
    rank: int
    is_new: bool
    is_win: bool
    attempts_count: int
    streak: int


async def ensure_user(
    db: Database,
    telegram_id: int,
    username: str | None = None,
    first_name: str | None = None,
    referred_by: str | None = None,
) -> None:
    await db.conn.execute(
        """INSERT INTO users (telegram_id, username, first_name, referred_by)
           VALUES (?, ?, ?, ?)
           ON CONFLICT(telegram_id) DO UPDATE SET
             username = COALESCE(excluded.username, username),
             first_name = COALESCE(excluded.first_name, first_name)""",
        (telegram_id, username, first_name, referred_by),
    )
    await db.conn.commit()


async def get_user(db: Database, telegram_id: int) -> dict:
    cur = await db.conn.execute("SELECT * FROM users WHERE telegram_id = ?", (telegram_id,))
    row = await cur.fetchone()
    if row is None:
        await ensure_user(db, telegram_id)
        cur = await db.conn.execute("SELECT * FROM users WHERE telegram_id = ?", (telegram_id,))
        row = await cur.fetchone()
    return dict(row)


async def set_lang(db: Database, telegram_id: int, lang: str) -> None:
    if lang not in ("ru", "en"):
        raise ValueError("lang must be 'ru' or 'en'")
    await ensure_user(db, telegram_id)
    await db.conn.execute(
        "UPDATE users SET lang_mode = ? WHERE telegram_id = ?", (lang, telegram_id)
    )
    await db.conn.commit()


def daily_game_key(lang: str, day_id: int | None = None) -> str:
    day = clock.current_day_id() if day_id is None else day_id
    return f"d:{day}:{lang}"


async def _find_rank(db: Database, game_key: str, raw_word: str, lang: str) -> tuple[str, int]:
    """Resolve a raw guess to (dict_word, rank) or raise WordNotFound."""
    candidates = lookup_candidates(raw_word, lang)
    if not candidates:
        raise WordNotFound(raw_word)
    if game_key.startswith("d:"):
        _, day_id, _ = game_key.split(":")
        for word in candidates:
            cur = await db.conn.execute(
                "SELECT rank FROM static.words_rank WHERE day_id = ? AND lang = ? AND word = ?",
                (int(day_id), lang, word),
            )
            row = await cur.fetchone()
            if row:
                return word, row["rank"]
    else:
        challenge_id = game_key.removeprefix("c:")
        for word in candidates:
            cur = await db.conn.execute(
                "SELECT rank FROM challenge_rank WHERE challenge_id = ? AND word = ?",
                (challenge_id, word),
            )
            row = await cur.fetchone()
            if row:
                return word, row["rank"]
    raise WordNotFound(raw_word)


async def _update_streak(db: Database, telegram_id: int, day_id: int) -> int:
    user = await get_user(db, telegram_id)
    if user["last_win_day"] == day_id:
        return user["streak"]
    streak = user["streak"] + 1 if user["last_win_day"] == day_id - 1 else 1
    await db.conn.execute(
        "UPDATE users SET streak = ?, last_win_day = ? WHERE telegram_id = ?",
        (streak, day_id, telegram_id),
    )
    await db.conn.commit()
    return streak


async def guess(
    db: Database, telegram_id: int, game_key: str, lang: str, raw_word: str
) -> GuessResult:
    await ensure_user(db, telegram_id)
    word, rank = await _find_rank(db, game_key, raw_word, lang)

    cur = await db.conn.execute(
        "SELECT rank FROM attempts WHERE telegram_id = ? AND game_key = ? AND word = ?",
        (telegram_id, game_key, word),
    )
    existing = await cur.fetchone()
    is_new = existing is None
    if is_new:
        await db.conn.execute(
            "INSERT INTO attempts (telegram_id, game_key, word, rank) VALUES (?, ?, ?, ?)",
            (telegram_id, game_key, word, rank),
        )
        await db.conn.commit()

    cur = await db.conn.execute(
        "SELECT COUNT(*) AS n FROM attempts WHERE telegram_id = ? AND game_key = ?",
        (telegram_id, game_key),
    )
    attempts_count = (await cur.fetchone())["n"]

    is_win = rank == 1
    streak = (await get_user(db, telegram_id))["streak"]
    if is_win and is_new and game_key.startswith("d:"):
        day_id = int(game_key.split(":")[1])
        streak = await _update_streak(db, telegram_id, day_id)

    return GuessResult(
        word=word,
        rank=rank,
        is_new=is_new,
        is_win=is_win,
        attempts_count=attempts_count,
        streak=streak,
    )


async def state(db: Database, telegram_id: int, game_key: str, lang: str) -> dict:
    user = await get_user(db, telegram_id)
    cur = await db.conn.execute(
        "SELECT word, rank FROM attempts WHERE telegram_id = ? AND game_key = ? ORDER BY rank",
        (telegram_id, game_key),
    )
    attempts = [{"word": r["word"], "rank": r["rank"]} for r in await cur.fetchall()]
    payload: dict = {
        "game_key": game_key,
        "lang": lang,
        "attempts": attempts,
        "attempts_count": len(attempts),
        "solved": any(a["rank"] == 1 for a in attempts),
        "streak": user["streak"],
    }
    if game_key.startswith("d:"):
        payload["day_no"] = int(game_key.split(":")[1])
    return payload


async def stats(db: Database, telegram_id: int) -> dict:
    user = await get_user(db, telegram_id)
    cur = await db.conn.execute(
        """SELECT
             COUNT(*) AS attempts_total,
             SUM(CASE WHEN rank = 1 THEN 1 ELSE 0 END) AS wins
           FROM attempts WHERE telegram_id = ?""",
        (telegram_id,),
    )
    row = await cur.fetchone()
    return {
        "attempts_total": row["attempts_total"] or 0,
        "wins": row["wins"] or 0,
        "streak": user["streak"],
        "lang_mode": user["lang_mode"],
    }
