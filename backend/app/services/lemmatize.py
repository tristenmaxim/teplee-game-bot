"""Lemmatization before rank lookup (CLAUDE.md, TECH_SPEC §5).

RU: pymorphy3 normal_form. EN: offline-built en_forms.json lookup.
Always lowercase and ё->е. The caller must try the normalized surface form
against the dictionary FIRST and fall back to the lemma: the guess dict
force-includes homographs ("пар", "сорока", "деньги") whose pymorphy lemma
points elsewhere (пара, сорок, деньга).
"""

import json
from functools import lru_cache
from pathlib import Path

import pymorphy3

# Mirror of generator FORCE_INCLUDE_RU quirks: pymorphy resolves these
# to lemmas the dictionary intentionally does not contain.
LEMMA_OVERRIDES_RU = {"деньга": "деньги"}

_morph = pymorphy3.MorphAnalyzer()
_en_forms: dict[str, str] = {}


def load_en_forms(path: str | Path) -> None:
    global _en_forms
    _en_forms = json.loads(Path(path).read_text(encoding="utf-8"))


def normalize(raw: str) -> str:
    return raw.strip().lower().replace("ё", "е")


@lru_cache(maxsize=4096)
def lemma_ru(word: str) -> str:
    nf = _morph.parse(word)[0].normal_form.replace("ё", "е")
    return LEMMA_OVERRIDES_RU.get(nf, nf)


def lemma_en(word: str) -> str:
    return _en_forms.get(word, word)


def lookup_candidates(raw: str, lang: str) -> list[str]:
    """Ordered dictionary-lookup candidates: surface form first, then lemma."""
    word = normalize(raw)
    if not word:
        return []
    lemma = lemma_ru(word) if lang == "ru" else lemma_en(word)
    return [word] if lemma == word else [word, lemma]
