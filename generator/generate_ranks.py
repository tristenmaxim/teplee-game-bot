"""Generate game_static.db from the curated answer dicts (docs/DATA_PIPELINE.md §4).

Run after hand-editing answer_candidates_{ru,en}.txt down to ~1000-1500 words each.
Shuffles each language's answer list with a fixed seed to build the day schedule,
then computes cosine-similarity ranks against the full guess-dict vector matrix.
"""

import argparse
import random
import sqlite3

import numpy as np

from common import DATA

SEED = 20260801
DAYS = 100

SCHEMA = """
CREATE TABLE words_rank (
  day_id  INTEGER NOT NULL,
  lang    TEXT    NOT NULL CHECK(lang IN ('ru','en')),
  word    TEXT    NOT NULL,
  rank    INTEGER NOT NULL,
  PRIMARY KEY (day_id, lang, word)
) WITHOUT ROWID;

CREATE TABLE daily_words (
  day_id INTEGER NOT NULL,
  lang   TEXT NOT NULL,
  word   TEXT NOT NULL,
  PRIMARY KEY (day_id, lang)
);
"""


def build_schedule(lang: str, days: int) -> list[str]:
    path = DATA / f"answer_candidates_{lang}.txt"
    answers = path.read_text(encoding="utf-8").splitlines()
    answers = [w.strip() for w in answers if w.strip()]

    rng = random.Random(SEED)
    rng.shuffle(answers)

    if len(answers) < days:
        print(f"[{lang}] warning: only {len(answers)} answer words, requested {days} days")
        return answers
    return answers[:days]


def generate_lang(conn: sqlite3.Connection, lang: str, days: int) -> None:
    vectors = np.load(DATA / f"vectors_{lang}.npy").astype(np.float32)
    vocab = (DATA / f"vocab_{lang}.txt").read_text(encoding="utf-8").splitlines()
    index = {w: i for i, w in enumerate(vocab)}

    schedule = build_schedule(lang, days)

    daily_rows = []
    rank_rows = []
    for day_id, answer in enumerate(schedule):
        if answer not in index:
            print(f"[{lang}] skip day {day_id}: '{answer}' not in guess dict")
            continue
        answer_idx = index[answer]
        sims = vectors @ vectors[answer_idx]
        order = np.argsort(-sims)
        for rank, word_idx in enumerate(order, start=1):
            rank_rows.append((day_id, lang, vocab[word_idx], rank))
        daily_rows.append((day_id, lang, answer))

    conn.executemany("INSERT INTO daily_words VALUES (?,?,?)", daily_rows)
    conn.executemany("INSERT INTO words_rank VALUES (?,?,?,?)", rank_rows)
    print(f"[{lang}] {len(daily_rows)} days, {len(rank_rows)} rank rows")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=DAYS)
    args = parser.parse_args()

    db_path = DATA / "game_static.db"
    db_path.unlink(missing_ok=True)

    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA)
    for lang in ("ru", "en"):
        generate_lang(conn, lang, args.days)
    conn.commit()
    conn.execute("VACUUM")
    conn.close()
    print(f"done -> {db_path}")


if __name__ == "__main__":
    main()
