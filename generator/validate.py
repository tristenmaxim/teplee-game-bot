"""Eyeball validation gate (docs/DATA_PIPELINE.md §5, mandatory before Этап 2).

Usage: uv run validate.py <word>
Prints the top-50 nearest guess-dict words by cosine similarity. Language is
auto-detected: any Cyrillic letter in the word selects the RU vectors, otherwise EN.
"""

import sys

import numpy as np

from common import DATA


def detect_lang(word: str) -> str:
    return "ru" if any("а" <= c <= "я" or c == "ё" for c in word.lower()) else "en"


def main() -> None:
    if len(sys.argv) != 2:
        print("usage: uv run validate.py <word>")
        raise SystemExit(1)
    word = sys.argv[1].lower().strip()

    lang = detect_lang(word)
    vectors = np.load(DATA / f"vectors_{lang}.npy").astype(np.float32)
    vocab = (DATA / f"vocab_{lang}.txt").read_text(encoding="utf-8").splitlines()

    if word not in vocab:
        print(f"'{word}' не найдено в guess-словаре ({lang}).")
        raise SystemExit(1)

    idx = vocab.index(word)
    sims = vectors @ vectors[idx]
    order = np.argsort(-sims)

    print(f"[{lang}] топ-50 ближайших к «{word}»:")
    rank = 0
    for i in order:
        if i == idx:
            continue
        rank += 1
        print(f"{rank:>3} {vocab[i]:<20} {sims[i]:.4f}")
        if rank >= 50:
            break


if __name__ == "__main__":
    main()
