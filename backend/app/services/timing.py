"""Timing/reaction game: stop a running clock as close as possible to a
random target (Mini App only, see ROADMAP — no bot text equivalent).

Solo rounds are free-play (any number of retries). Challenge rounds are
one-shot per user (server-enforced) so comparisons stay fair. Elapsed time
is measured server-side from the request that started the round to the
request that stopped it — trusting a client-reported duration would make
the whole game trivially gameable.

game_key: 'solo' | 't:<challenge_id>'.
"""

import random
import secrets
import time

import aiosqlite

from app.db import Database

MIN_TARGET_MS = 2000
MAX_TARGET_MS = 8000
TTL_DAYS = 7
_ID_RETRIES = 3

_RATING_THRESHOLDS = [
    (50, "🎯 Идеально!"),
    (200, "🔥 Отлично!"),
    (500, "👍 Неплохо"),
    (1500, "🙂 Мимо"),
]


class RoundNotFound(Exception):
    """No such in-progress round for this user."""


class AlreadyPlayed(Exception):
    """This challenge already has a completed round for this user."""


class ChallengeNotFound(Exception):
    pass


def rating(delta_ms: int) -> str:
    for threshold, label in _RATING_THRESHOLDS:
        if delta_ms <= threshold:
            return label
    return "😅 Далеко"


def _now_ms() -> int:
    return int(time.time() * 1000)


async def start_round(
    db: Database, telegram_id: int, mode: str, challenge_id: str | None
) -> dict:
    """Returns {round_id, target_ms, mode}."""
    if challenge_id is not None:
        meta = await challenge_meta(db, challenge_id)
        if meta is None:
            raise ChallengeNotFound(challenge_id)
        cur = await db.conn.execute(
            "SELECT 1 FROM timing_results WHERE challenge_id = ? AND telegram_id = ?",
            (challenge_id, telegram_id),
        )
        if await cur.fetchone() is not None:
            raise AlreadyPlayed(challenge_id)
        target_ms = meta["target_ms"]
        mode = meta["mode"]
        game_key = f"t:{challenge_id}"
    else:
        target_ms = random.randint(MIN_TARGET_MS, MAX_TARGET_MS)
        game_key = "solo"

    round_id = secrets.token_urlsafe(8)
    await db.conn.execute(
        """INSERT INTO timing_rounds
           (round_id, telegram_id, game_key, mode, target_ms, started_at_ms)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (round_id, telegram_id, game_key, mode, target_ms, _now_ms()),
    )
    await db.conn.commit()
    return {"round_id": round_id, "target_ms": target_ms, "mode": mode}


async def stop_round(db: Database, telegram_id: int, round_id: str) -> dict:
    """Returns {elapsed_ms, target_ms, delta_ms, rating}."""
    cur = await db.conn.execute(
        "SELECT * FROM timing_rounds WHERE round_id = ? AND telegram_id = ?",
        (round_id, telegram_id),
    )
    row = await cur.fetchone()
    if row is None or row["stopped_at_ms"] is not None:
        raise RoundNotFound(round_id)

    now_ms = _now_ms()
    elapsed_ms = now_ms - row["started_at_ms"]
    delta_ms = abs(elapsed_ms - row["target_ms"])
    await db.conn.execute(
        "UPDATE timing_rounds SET elapsed_ms = ?, stopped_at_ms = ? WHERE round_id = ?",
        (elapsed_ms, now_ms, round_id),
    )
    if row["game_key"].startswith("t:"):
        challenge_id = row["game_key"].removeprefix("t:")
        await db.conn.execute(
            """INSERT OR IGNORE INTO timing_results
               (challenge_id, telegram_id, elapsed_ms, delta_ms)
               VALUES (?, ?, ?, ?)""",
            (challenge_id, telegram_id, elapsed_ms, delta_ms),
        )
    await db.conn.commit()

    return {
        "elapsed_ms": elapsed_ms,
        "target_ms": row["target_ms"],
        "delta_ms": delta_ms,
        "rating": rating(delta_ms),
    }


async def create_challenge(db: Database, creator_id: int, mode: str) -> str:
    target_ms = random.randint(MIN_TARGET_MS, MAX_TARGET_MS)
    last_error: Exception | None = None
    for _ in range(_ID_RETRIES):
        challenge_id = secrets.token_urlsafe(6)
        try:
            await db.conn.execute(
                """INSERT INTO timing_challenges (id, creator_id, mode, target_ms, expires_at)
                   VALUES (?, ?, ?, ?, datetime('now', ?))""",
                (challenge_id, creator_id, mode, target_ms, f"+{TTL_DAYS} days"),
            )
        except aiosqlite.IntegrityError as exc:
            last_error = exc
            continue
        await db.conn.commit()
        return challenge_id
    raise last_error  # pragma: no cover — astronomically unlikely


async def challenge_meta(db: Database, challenge_id: str) -> dict | None:
    cur = await db.conn.execute(
        """SELECT id, creator_id, mode, target_ms FROM timing_challenges
           WHERE id = ? AND expires_at > datetime('now')""",
        (challenge_id,),
    )
    row = await cur.fetchone()
    return dict(row) if row else None


async def challenge_results(db: Database, challenge_id: str) -> list[dict]:
    cur = await db.conn.execute(
        """SELECT r.telegram_id, r.elapsed_ms, r.delta_ms, u.username, u.first_name
           FROM timing_results r JOIN users u ON u.telegram_id = r.telegram_id
           WHERE r.challenge_id = ? ORDER BY r.delta_ms ASC""",
        (challenge_id,),
    )
    rows = await cur.fetchall()
    return [
        {
            "label": f"@{r['username']}" if r["username"] else (r["first_name"] or "Игрок"),
            "elapsed_ms": r["elapsed_ms"],
            "delta_ms": r["delta_ms"],
        }
        for r in rows
    ]
