"""Build the guess dictionary + embedding matrix for one language.

docs/DATA_PIPELINE.md §2: frequency list -> filters -> noun morphology -> has embedding
-> vectors_<lang>.npy (float16, L2-normalized) + vocab_<lang>.txt (row order matches).
"""

import argparse
from collections import Counter
from functools import lru_cache

import numpy as np
import pymorphy3
from nltk import pos_tag
from nltk.corpus import brown, wordnet as wn
from wordfreq import iter_wordlist

from common import DATA, MODELS, load_blacklist, normalize, passes_basic_filters

MAX_WORDS = 40_000
CANDIDATE_BUFFER = 1.5  # collect this many extra candidates before the embedding-existence cut

PROPER_NOUN_TAGS = {"Name", "Surn", "Patr", "Geox", "Orgn"}
BROWN_MIN_SAMPLES = 5
BROWN_MIN_NOUN_FRAC = 0.5

_morph = pymorphy3.MorphAnalyzer()


def is_valid_noun_ru(word: str) -> bool:
    tag = _morph.parse(word)[0].tag
    if "NOUN" not in tag:
        return False
    if PROPER_NOUN_TAGS & tag.grammemes:
        return False
    if "nomn" not in tag:
        return False
    if "sing" not in tag and "Pltm" not in tag:
        return False
    return True


@lru_cache(maxsize=1)
def _brown_pos_counts() -> dict[str, Counter]:
    counts: dict[str, Counter] = {}
    for word, tag in brown.tagged_words(tagset="universal"):
        counts.setdefault(word.lower(), Counter())[tag] += 1
    return counts


def _is_verb_dominant(word: str) -> bool:
    """A single word out of context is POS-ambiguous (pos_tag/WordNet alone let
    verbs like "think"/"want"/"found" through as "NN"). Cross-check against real
    tagged usage in the Brown corpus; only reject when we have enough samples to
    be confident the noun sense isn't the dominant one. Unattested/modern words
    (not in the 1961 Brown corpus) are left to the embedding + manual eyeball gate."""
    counts = _brown_pos_counts().get(word)
    if not counts:
        return False
    total = sum(counts.values())
    if total < BROWN_MIN_SAMPLES:
        return False
    return (counts.get("NOUN", 0) / total) < BROWN_MIN_NOUN_FRAC


def is_valid_noun_en(word: str) -> bool:
    (_, pos), = pos_tag([word])
    if pos != "NN":
        return False
    if not wn.synsets(word, pos=wn.NOUN):
        return False
    if _is_verb_dominant(word):
        return False
    return True


def collect_candidates(lang: str, cap: int) -> list[str]:
    blacklist = load_blacklist(lang)
    is_valid_noun = is_valid_noun_ru if lang == "ru" else is_valid_noun_en

    seen: set[str] = set()
    candidates: list[str] = []
    for raw_word in iter_wordlist(lang, wordlist="best"):
        word = normalize(raw_word, lang)
        if word in seen:
            continue
        if not passes_basic_filters(word, blacklist):
            continue
        if not is_valid_noun(word):
            continue
        seen.add(word)
        candidates.append(word)
        if len(candidates) >= cap:
            break
    return candidates


def load_navec_vector_fn(path):
    from navec import Navec

    navec = Navec.load(path)

    def get(word: str) -> np.ndarray | None:
        return navec.get(word)

    return get


def load_fasttext_vectors(path, wanted: set[str]) -> dict[str, np.ndarray]:
    found: dict[str, np.ndarray] = {}
    with open(path, encoding="utf-8") as f:
        next(f)  # header: "<n_words> <dim>"
        for line in f:
            parts = line.rstrip("\n").split(" ")
            word = parts[0]
            if word in wanted and word not in found:
                found[word] = np.array(parts[1:], dtype=np.float32)
                if len(found) == len(wanted):
                    break
    return found


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--lang", choices=["ru", "en"], required=True)
    parser.add_argument("--max-words", type=int, default=MAX_WORDS)
    args = parser.parse_args()

    cap = int(args.max_words * CANDIDATE_BUFFER)
    print(f"[{args.lang}] collecting up to {cap} noun candidates...")
    candidates = collect_candidates(args.lang, cap)
    print(f"[{args.lang}] {len(candidates)} candidates passed filters")

    words: list[str] = []
    vecs: list[np.ndarray] = []

    if args.lang == "ru":
        get_vec = load_navec_vector_fn(MODELS / "navec_hudlit_v1_12B_500K_300d_100q.tar")
        for w in candidates:
            v = get_vec(w)
            if v is not None:
                words.append(w)
                vecs.append(v.astype(np.float32))
            if len(words) >= args.max_words:
                break
    else:
        wanted = set(candidates)
        print(f"[{args.lang}] scanning fastText vectors for {len(wanted)} words...")
        found = load_fasttext_vectors(MODELS / "crawl-300d-2M.vec", wanted)
        for w in candidates:
            if w in found:
                words.append(w)
                vecs.append(found[w])
            if len(words) >= args.max_words:
                break

    print(f"[{args.lang}] {len(words)} words have embeddings, writing artifacts...")

    matrix = np.stack(vecs).astype(np.float32)
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    matrix = (matrix / norms).astype(np.float16)

    DATA.mkdir(parents=True, exist_ok=True)
    np.save(DATA / f"vectors_{args.lang}.npy", matrix)
    with open(DATA / f"vocab_{args.lang}.txt", "w", encoding="utf-8") as f:
        f.write("\n".join(words) + "\n")

    print(f"[{args.lang}] done: {len(words)} words -> vectors_{args.lang}.npy / vocab_{args.lang}.txt")


if __name__ == "__main__":
    main()
