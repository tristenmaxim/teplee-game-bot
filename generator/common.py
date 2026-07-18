"""Shared paths and word filters for the data pipeline (docs/DATA_PIPELINE.md §2)."""

from pathlib import Path

DATA = Path(__file__).parent / "data"
MODELS = DATA / "models"

MIN_LEN = 3
MAX_LEN = 15


def load_blacklist(lang: str) -> set[str]:
    path = DATA / f"blacklist_{lang}.txt"
    with open(path, encoding="utf-8") as f:
        return {line.strip().lower() for line in f if line.strip()}


def normalize(word: str, lang: str) -> str:
    w = word.lower()
    if lang == "ru":
        w = w.replace("ё", "е")
    return w


def passes_basic_filters(word: str, blacklist: set[str]) -> bool:
    if not (MIN_LEN <= len(word) <= MAX_LEN):
        return False
    if not word.isalpha():
        return False
    if word in blacklist:
        return False
    return True
