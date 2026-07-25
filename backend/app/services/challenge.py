"""Challenge creation/lifecycle (PRD §4).

game.py's guess()/state()/hint() already handle 'c:<id>' game_keys via the
challenge_rank table (see _find_rank) — this module only owns what game.py
doesn't: creating a challenge (ranking the creator's word) and its side tables.
"""

import secrets

import aiosqlite

from app.db import Database
from app.services import vectors
from app.services.game import WordNotFound
from app.services.lemmatize import lookup_candidates

MAX_ACTIVE = 5  # PRD §4: max active (non-expired) challenges per creator
TTL_DAYS = 7  # PRD §4: challenge lifetime

_ID_RETRIES = 3


class TooManyChallenges(Exception):
    """Creator already has MAX_ACTIVE non-expired challenges."""


async def create(db: Database, data_dir: str, creator_id: int, lang: str, raw_word: str) -> str:
    """Rank raw_word, create the challenge row + its full challenge_rank table.

    Raises TooManyChallenges if the creator is at MAX_ACTIVE, WordNotFound if
    raw_word isn't in the guess dictionary. VectorsUnavailable propagates
    uncaught for the caller to handle.
    """
    cur = await db.conn.execute(
        """SELECT COUNT(*) AS n FROM challenges
           WHERE creator_id = ? AND expires_at > datetime('now')""",
        (creator_id,),
    )
    if (await cur.fetchone())["n"] >= MAX_ACTIVE:
        raise TooManyChallenges(creator_id)

    ranking = None
    word = None
    for candidate in lookup_candidates(raw_word, lang):
        ranking = await vectors.rank_against(data_dir, lang, candidate)
        if ranking is not None:
            word = candidate
            break
    if ranking is None:
        raise WordNotFound(raw_word)

    last_error: Exception | None = None
    for _ in range(_ID_RETRIES):
        challenge_id = secrets.token_urlsafe(6)
        try:
            await db.conn.execute(
                """INSERT INTO challenges (id, creator_id, lang, word, expires_at)
                   VALUES (?, ?, ?, ?, datetime('now', ?))""",
                (challenge_id, creator_id, lang, word, f"+{TTL_DAYS} days"),
            )
        except aiosqlite.IntegrityError as exc:
            last_error = exc
            continue
        await db.conn.executemany(
            "INSERT INTO challenge_rank (challenge_id, word, rank) VALUES (?, ?, ?)",
            [(challenge_id, w, r) for w, r in ranking],
        )
        await db.conn.commit()
        return challenge_id
    raise last_error  # pragma: no cover — astronomically unlikely


async def get_meta(db: Database, challenge_id: str) -> dict | None:
    """Returns {"id", "creator_id", "lang", "word"} if not expired, else None.

    Warning for callers: this is trusted/internal — `word` must never be
    forwarded to anyone but the creator (it's the secret answer).
    """
    cur = await db.conn.execute(
        """SELECT id, creator_id, lang, word FROM challenges
           WHERE id = ? AND expires_at > datetime('now')""",
        (challenge_id,),
    )
    row = await cur.fetchone()
    return dict(row) if row else None


async def record_win(db: Database, challenge_id: str, telegram_id: int, attempts: int) -> None:
    """Idempotent: relies on challenge_results' PRIMARY KEY to no-op on repeat."""
    await db.conn.execute(
        """INSERT OR IGNORE INTO challenge_results (challenge_id, telegram_id, attempts)
           VALUES (?, ?, ?)""",
        (challenge_id, telegram_id, attempts),
    )
    await db.conn.commit()
