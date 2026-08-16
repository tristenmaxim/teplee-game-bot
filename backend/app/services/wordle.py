"""Wordle-style daily game: guess a 5-letter RU word in 6 tries, exact-match feedback.

game_key: 'w:<day_id>'. Unlike the semantic daily game, no vectors/ranks needed —
feedback is a pure function of (guess, answer). The answer schedule reuses the
project's existing curated 5-letter subset of answer_candidates_ru.txt (bundled
in app/wordle_data/), shuffled once with a fixed seed — same idea as
generate_ranks.py's daily schedule, just computed in-process since there's no
vector matrix to bake into game_static.db for this game.
"""

import random
from dataclasses import dataclass
from pathlib import Path

from app.db import Database
from app.services import clock
from app.services.game import ensure_user, get_user

DATA_DIR = Path(__file__).parent.parent / "wordle_data"
SEED = 20260801
WORD_LEN = 5
MAX_ATTEMPTS = 6


class InvalidGuess(Exception):
    """Not a WORD_LEN-letter word in the guess dictionary."""


class GameOver(Exception):
    """Already solved, or all attempts used — no more guesses accepted."""


def _load(name: str) -> list[str]:
    return [w for w in (DATA_DIR / name).read_text(encoding="utf-8").splitlines() if w]


_ANSWERS = _load("answers_ru.txt")
random.Random(SEED).shuffle(_ANSWERS)
_GUESS_WORDS = frozenset(_load("guesses_ru.txt")) | frozenset(_ANSWERS)


def _normalize(word: str) -> str:
    return word.strip().lower().replace("ё", "е")


def daily_word(day_id: int) -> str:
    return _ANSWERS[day_id % len(_ANSWERS)]


def daily_game_key(day_id: int | None = None) -> str:
    day = clock.current_day_id() if day_id is None else day_id
    return f"w:{day}"


def feedback(guess: str, answer: str) -> list[str]:
    """Per-letter 'hit' | 'present' | 'miss', standard two-pass Wordle algorithm."""
    result = [""] * len(guess)
    remaining = list(answer)
    for i, ch in enumerate(guess):
        if i < len(answer) and ch == answer[i]:
            result[i] = "hit"
            remaining[i] = None
    for i, ch in enumerate(guess):
        if result[i]:
            continue
        if ch in remaining:
            result[i] = "present"
            remaining[remaining.index(ch)] = None
        else:
            result[i] = "miss"
    return result


async def _update_streak(db: Database, telegram_id: int, day_id: int) -> int:
    user = await get_user(db, telegram_id)
    if user["last_wordle_win_day"] == day_id:
        return user["wordle_streak"]
    streak = user["wordle_streak"] + 1 if user["last_wordle_win_day"] == day_id - 1 else 1
    await db.conn.execute(
        "UPDATE users SET wordle_streak = ?, last_wordle_win_day = ? WHERE telegram_id = ?",
        (streak, day_id, telegram_id),
    )
    await db.conn.commit()
    return streak


@dataclass
class WordleAttempt:
    word: str
    feedback: list[str]


@dataclass
class WordleGuessResult:
    attempts: list[WordleAttempt]
    solved: bool
    game_over: bool
    streak: int


async def _attempt_rows(db: Database, telegram_id: int, game_key: str) -> list[str]:
    cur = await db.conn.execute(
        "SELECT word FROM wordle_attempts WHERE telegram_id = ? AND game_key = ? "
        "ORDER BY attempt_no",
        (telegram_id, game_key),
    )
    return [row["word"] for row in await cur.fetchall()]


async def guess(db: Database, telegram_id: int, game_key: str, raw_word: str) -> WordleGuessResult:
    await ensure_user(db, telegram_id)
    day_id = int(game_key.removeprefix("w:"))
    answer = daily_word(day_id)

    prior = await _attempt_rows(db, telegram_id, game_key)
    if answer in prior or len(prior) >= MAX_ATTEMPTS:
        raise GameOver

    word = _normalize(raw_word)
    if len(word) != WORD_LEN or word not in _GUESS_WORDS:
        raise InvalidGuess(raw_word)

    attempt_no = len(prior) + 1
    await db.conn.execute(
        "INSERT INTO wordle_attempts (telegram_id, game_key, attempt_no, word) VALUES (?, ?, ?, ?)",
        (telegram_id, game_key, attempt_no, word),
    )
    await db.conn.commit()

    solved = word == answer
    streak = (await get_user(db, telegram_id))["wordle_streak"]
    if solved:
        streak = await _update_streak(db, telegram_id, day_id)

    words = [*prior, word]
    return WordleGuessResult(
        attempts=[WordleAttempt(w, feedback(w, answer)) for w in words],
        solved=solved,
        game_over=solved or attempt_no >= MAX_ATTEMPTS,
        streak=streak,
    )


async def state(db: Database, telegram_id: int, game_key: str) -> dict:
    day_id = int(game_key.removeprefix("w:"))
    answer = daily_word(day_id)
    words = await _attempt_rows(db, telegram_id, game_key)
    solved = answer in words
    game_over = solved or len(words) >= MAX_ATTEMPTS
    user = await get_user(db, telegram_id)
    return {
        "game_key": game_key,
        "day_no": day_id,
        "attempts": [{"word": w, "feedback": feedback(w, answer)} for w in words],
        "attempts_count": len(words),
        "solved": solved,
        "game_over": game_over,
        "streak": user["wordle_streak"],
        "word_length": WORD_LEN,
        "max_attempts": MAX_ATTEMPTS,
        "answer": answer if game_over else None,
    }
