import json
import os

BOT_TOKEN = "12345:TEST_TOKEN"
os.environ.setdefault("BOT_TOKEN", BOT_TOKEN)
os.environ.setdefault("BOT_USERNAME", "teplee_bot")

import aiosqlite  # noqa: E402
import numpy as np  # noqa: E402
import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402

from app.db import Database  # noqa: E402
from app.services import lemmatize  # noqa: E402

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


@pytest.fixture
def fake_vectors(tmp_path):
    """Tiny hand-crafted RU vector matrix + vocab for testing vectors.py/challenge.py
    without a real 15-40MB .npy file. No EN files are written, so tests can also
    exercise the VectorsUnavailable path for an unsupported language."""
    from app.services import vectors as vectors_module

    vocab = ["кот", "собака", "щенок", "камень", "облако"]
    # Two clearly-separated clusters: кот/собака/щенок ("animals") close
    # together, камень/облако ("nature/object") close together and far from
    # the animal cluster — an unambiguous rank-order for assertions.
    raw = np.array(
        [
            [1.0, 0.9, 0.0, 0.0],  # кот
            [0.95, 1.0, 0.1, 0.0],  # собака
            [0.9, 0.95, 0.05, 0.0],  # щенок
            [0.0, 0.0, 1.0, 0.9],  # камень
            [0.0, 0.05, 0.95, 1.0],  # облако
        ]
    )
    normed = raw / np.linalg.norm(raw, axis=1, keepdims=True)

    np.save(tmp_path / "vectors_ru.npy", normed.astype(np.float16))
    (tmp_path / "vocab_ru.txt").write_text("\n".join(vocab), encoding="utf-8")

    vectors_module.clear_cache()
    yield str(tmp_path)
    vectors_module.clear_cache()
