"""SQLite layer: one writer connection, WAL, static tables via ATTACH (TECH_SPEC §3).

All writes go through the single aiosqlite connection owned by Database;
at our load a global writer is simpler and safer than a pool.
"""

from pathlib import Path

import aiosqlite

MIGRATIONS = """
CREATE TABLE IF NOT EXISTS users (
  telegram_id  INTEGER PRIMARY KEY,
  username     TEXT,
  first_name   TEXT,
  lang_mode    TEXT DEFAULT 'ru',
  notifications INTEGER DEFAULT 1,
  game_message_id INTEGER,
  active_game  TEXT,
  streak       INTEGER DEFAULT 0,
  last_win_day INTEGER,
  referred_by  TEXT,
  created_at   TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS attempts (
  telegram_id INTEGER NOT NULL,
  game_key    TEXT    NOT NULL,
  word        TEXT    NOT NULL,
  rank        INTEGER NOT NULL,
  created_at  TEXT DEFAULT (datetime('now')),
  PRIMARY KEY (telegram_id, game_key, word)
);
CREATE INDEX IF NOT EXISTS idx_attempts ON attempts(telegram_id, game_key);

CREATE TABLE IF NOT EXISTS challenges (
  id          TEXT PRIMARY KEY,
  creator_id  INTEGER NOT NULL,
  lang        TEXT NOT NULL,
  word        TEXT NOT NULL,
  created_at  TEXT DEFAULT (datetime('now')),
  expires_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS challenge_rank (
  challenge_id TEXT NOT NULL,
  word         TEXT NOT NULL,
  rank         INTEGER NOT NULL,
  PRIMARY KEY (challenge_id, word)
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS challenge_results (
  challenge_id TEXT NOT NULL,
  telegram_id  INTEGER NOT NULL,
  attempts     INTEGER NOT NULL,
  won_at       TEXT DEFAULT (datetime('now')),
  PRIMARY KEY (challenge_id, telegram_id)
);
"""


class Database:
    def __init__(self, conn: aiosqlite.Connection):
        self.conn = conn

    @classmethod
    async def open(cls, db_path: str, static_db_path: str | None = None) -> "Database":
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        conn = await aiosqlite.connect(f"file:{db_path}?mode=rwc", uri=True)
        conn.row_factory = aiosqlite.Row
        await conn.execute("PRAGMA journal_mode=WAL")
        await conn.execute("PRAGMA synchronous=NORMAL")
        await conn.execute("PRAGMA busy_timeout=5000")
        await conn.execute("PRAGMA foreign_keys=ON")
        if static_db_path:
            # mode=ro keeps the generated rank tables untouchable at runtime
            await conn.execute(
                "ATTACH DATABASE ? AS static", (f"file:{static_db_path}?mode=ro",)
            )
        await conn.executescript(MIGRATIONS)
        await conn.commit()
        return cls(conn)

    async def close(self) -> None:
        await self.conn.close()
