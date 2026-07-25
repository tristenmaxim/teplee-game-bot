"""Embedding lookup for ranking a challenge word against the full guess dict.

Lazy per-language: most days create zero challenges, so nothing is loaded at
startup on a 1GB box. Matrices stay resident as float16 (as shipped); only the
two operands of a given matmul are cast to float32, since float16 matmul isn't
BLAS-accelerated and would be slower on a single CPU.
"""

import asyncio
from pathlib import Path

import numpy as np


class VectorsUnavailable(Exception):
    """vectors_<lang>.npy / vocab_<lang>.txt not found under data_dir."""


_cache: dict[str, tuple[np.ndarray, list[str], dict[str, int]]] = {}


def clear_cache() -> None:
    """Test-only hook to reset the lazy-load cache between tests."""
    _cache.clear()


def _load_sync(data_dir: str, lang: str) -> tuple[np.ndarray, list[str], dict[str, int]]:
    vectors_path = Path(data_dir) / f"vectors_{lang}.npy"
    vocab_path = Path(data_dir) / f"vocab_{lang}.txt"
    if not vectors_path.exists() or not vocab_path.exists():
        raise VectorsUnavailable(lang)
    vectors = np.load(vectors_path)
    vocab = vocab_path.read_text(encoding="utf-8").splitlines()
    index = {w: i for i, w in enumerate(vocab)}
    return vectors, vocab, index


async def _get(data_dir: str, lang: str) -> tuple[np.ndarray, list[str], dict[str, int]]:
    if lang not in _cache:
        _cache[lang] = await asyncio.to_thread(_load_sync, data_dir, lang)
    return _cache[lang]


def _rank_sync(vectors: np.ndarray, vocab: list[str], word_idx: int) -> list[tuple[str, int]]:
    target = vectors[word_idx].astype(np.float32)
    sims = vectors.astype(np.float32) @ target
    order = np.argsort(-sims)
    return [(vocab[idx], rank) for rank, idx in enumerate(order, start=1)]


async def rank_against(data_dir: str, lang: str, word: str) -> list[tuple[str, int]] | None:
    """Rank the whole vocab by cosine similarity to `word` (rank 1 = itself).

    Returns None if `word` isn't in this language's vocab index — the vocab
    index IS the guess dictionary, so this doubles as membership check.
    """
    vectors, vocab, index = await _get(data_dir, lang)
    word_idx = index.get(word)
    if word_idx is None:
        return None
    return await asyncio.to_thread(_rank_sync, vectors, vocab, word_idx)
