import json

import aiosqlite
import pytest
import pytest_asyncio

from app.db import Database
from app.services import lemmatize

BOT_TOKEN = "12345:TEST_TOKEN"

STATIC_SCHEMA = """
CREATE TABLE words_rank (
  day_id INTEGER NOT NULL, lang TEXT NOT NULL, word TEXT NOT NULL, rank INTEGER NOT NULL,
  PRIMARY KEY (day_id, lang, word)
) WITHOUT ROWID;
CREATE TABLE daily_words (
  day_id INTEGER NOT NULL, lang TEXT NOT NULL, word TEXT NOT NULL,
  PRIMARY KEY (day_id, lang)
);
"""

# day 0 RU answer=кот, day 0 EN answer=cat, day 1 RU answer=собака
STATIC_ROWS = [
    (0, "ru", "кот", 1),
    (0, "ru", "кошка", 2),
    (0, "ru", "собака", 3),
    (0, "ru", "деньги", 100),
    (0, "ru", "пар", 200),
    (0, "en", "cat", 1),
    (0, "en", "dog", 2),
    (0, "en", "apple", 500),
    (1, "ru", "собака", 1),
    (1, "ru", "кот", 5),
    (3, "ru", "кот", 1),
]


@pytest_asyncio.fixture
async def db(tmp_path):
    static_path = tmp_path / "game_static.db"
    conn = await aiosqlite.connect(static_path)
    await conn.executescript(STATIC_SCHEMA)
    await conn.executemany("INSERT INTO words_rank VALUES (?, ?, ?, ?)", STATIC_ROWS)
    await conn.executemany(
        "INSERT INTO daily_words VALUES (?, ?, ?)",
        [(0, "ru", "кот"), (0, "en", "cat"), (1, "ru", "собака")],
    )
    await conn.commit()
    await conn.close()

    database = await Database.open(str(tmp_path / "game.db"), str(static_path))
    yield database
    await database.close()


@pytest.fixture
def en_forms(tmp_path):
    path = tmp_path / "en_forms.json"
    path.write_text(json.dumps({"cats": "cat", "dogs": "dog", "apples": "apple"}))
    lemmatize.load_en_forms(path)
    yield
    path.write_text("{}")
    lemmatize.load_en_forms(path)
