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
  last_challenge_id TEXT,
  awaiting_challenge INTEGER NOT NULL DEFAULT 0,
  created_at   TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS attempts (
  telegram_id INTEGER NOT NULL,
  game_key    TEXT    NOT NULL,
  word        TEXT    NOT NULL,
  rank        INTEGER NOT NULL,
  via_hint    INTEGER NOT NULL DEFAULT 0,
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

CREATE INDEX IF NOT EXISTS idx_challenges_creator ON challenges(creator_id, expires_at);

CREATE TABLE IF NOT EXISTS challenge_results (
  challenge_id TEXT NOT NULL,
  telegram_id  INTEGER NOT NULL,
  attempts     INTEGER NOT NULL,
  won_at       TEXT DEFAULT (datetime('now')),
  PRIMARY KEY (challenge_id, telegram_id)
);

CREATE TABLE IF NOT EXISTS bot_texts (
  key        TEXT PRIMARY KEY,
  value      TEXT NOT NULL,
  updated_at TEXT DEFAULT (datetime('now'))
);
"""


async def _add_column_if_missing(
    conn: aiosqlite.Connection, table: str, column: str, decl: str
) -> None:
    """Idempotent column-migration for a live prod DB.

    CREATE TABLE IF NOT EXISTS in MIGRATIONS only creates missing tables, it
    won't add a column to a table that already exists. SQLite's ADD COLUMN IF
    NOT EXISTS is a newer feature (unverified on the prod container), so we
    check PRAGMA table_info instead — portable across SQLite versions.
    """
    cur = await conn.execute(f"PRAGMA table_info({table})")
    cols = {row["name"] for row in await cur.fetchall()}
    if column not in cols:
        await conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")


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
        await _add_column_if_missing(conn, "attempts", "via_hint", "INTEGER NOT NULL DEFAULT 0")
        await _add_column_if_missing(conn, "users", "last_challenge_id", "TEXT")
        await _add_column_if_missing(
            conn, "users", "awaiting_challenge", "INTEGER NOT NULL DEFAULT 0"
        )
        await conn.commit()
        return cls(conn)

    async def close(self) -> None:
        await self.conn.close()
