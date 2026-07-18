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

# Abbr: pymorphy3 tags "руб"/"сми"/"стр" as abbreviations — never guessable words.
EXCLUDED_TAGS = {"Name", "Surn", "Patr", "Geox", "Orgn", "Abbr"}

# Fragments of proper names / brands / adjective-nouns that pymorphy3 tags as plain
# nouns (web-corpus frequency artifacts: "санкт-петербург", "динамо", "нью-йорк"...).
STOPLIST_RU = {
    "санкт", "динамо", "сити", "экс", "нью", "лос", "сан", "дель", "ван", "фон",
    "рада", "белые", "спартак", "зенит", "реал",
    "водица",  # diminutive below the cosine gate
}
BROWN_MIN_SAMPLES = 5
BROWN_MIN_NOUN_FRAC = 0.5

# Words the morphology filters reject for structural reasons but that players
# unquestionably expect: "деньги" (pymorphy lemma is archaic "деньга") and
# common homographs whose own-lemma probability mass is dominated by another
# reading ("пар" by пара, "сорока" by сорок, "берет" by брать). The backend
# lemmatizer must look words up as-is before falling back to normal_form (Этап 2).
FORCE_INCLUDE_RU = {"деньги", "пар", "куб", "майка", "сорока", "берет", "том"}

_morph = pymorphy3.MorphAnalyzer()


def is_valid_noun_ru(word: str) -> bool:
    if word in FORCE_INCLUDE_RU:
        return True
    if word in STOPLIST_RU:
        return False
    # Web-corpus fragments ("компани", "перев") parse as nouns via prediction;
    # require a real dictionary entry. Costs a few neologisms — acceptable.
    if not _morph.word_is_known(word):
        return False
    # Check every parse, not just the highest-scored one: for "хлеб" the top
    # parse is accusative, for "море" locative — taking parse[0] alone silently
    # drops scores of common nouns. Also require normal_form == word so the
    # dictionary only holds lemmas (backend lemmatizes guesses the same way).
    # But demand real probability mass behind the own-lemma reading: "вод"/"лет"
    # sneak in via junk lexemes scored 0.0-0.12, while legit homonyms like
    # "душ" (shower vs душа gen.pl) carry >= 0.25.
    own_lemma_mass = 0.0
    has_valid_nomn = False
    for parse in _morph.parse(word):
        tag = parse.tag
        if "NOUN" not in tag:
            continue
        nf = parse.normal_form.replace("ё", "е")
        # pymorphy3 lemmatizes -ье nouns to their archaic -ие twin
        # ("счастье" -> "счастие"); accept the modern surface form.
        if nf != word and not (word.endswith("ье") and nf == word[:-2] + "ие"):
            continue
        own_lemma_mass += parse.score
        if (
            not (EXCLUDED_TAGS & tag.grammemes)
            and "nomn" in tag
            and ("sing" in tag or "Pltm" in tag)
        ):
            has_valid_nomn = True
    return has_valid_nomn and own_lemma_mass >= 0.15


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


# Pet-name diminutives with no derivable base form ("kitty" -> cat),
# plus variant spellings / abbreviations WordNet happens to contain.
STOPLIST_EN = {
    "doggy", "doggo", "kitty", "mommy", "momma", "mummy", "daddy", "granny",
    "tummy", "piggy", "horsey", "birdy", "potty", "kiddo", "kiddie",
    "cigaret", "diam", "musci", "irak",
    # foreign loans and slang that read as junk next to plain answers
    "agua", "dinero", "moolah", "bunce", "gobs", "carfare", "lucre",
}


def is_valid_noun_en(word: str) -> bool:
    if word in STOPLIST_EN:
        return False
    (_, pos), = pos_tag([word])
    if pos != "NN":
        return False
    if not wn.synsets(word, pos=wn.NOUN):
        return False
    # Reject inflected forms that only reach WordNet via morphy ("lucys" -> lucy,
    # "media" -> medium): the guess dict holds lemmas, en_forms.json maps the rest.
    if (wn.morphy(word, wn.NOUN) or word) != word:
        return False
    if _is_verb_dominant(word):
        return False
    return True


# --- Diminutive post-pass (docs/DATA_PIPELINE.md §2: "котик" рядом с "кот" бесят) ---
# A word is dropped as a diminutive only when ALL three hold: it matches a suffix
# rule, the derived base is a more frequent word already in the dictionary, and the
# two vectors are semantically close. The cosine gate protects lexicalized
# false positives (песок/пёс, замок/зам, cookie/cook stay in).

DIM_COSINE_MIN = 0.42
DIM_BASE_MIN_LEN = 2

# (suffix, base replacements), longest suffix first
RU_DIM_RULES: list[tuple[str, list[str]]] = [
    ("очек", ["ок"]),
    ("ичок", ["ик"]),
    ("очка", ["а", "ка"]),
    ("ечка", ["а", "ка"]),
    ("ичка", ["а"]),
    ("ушка", ["а", ""]),
    ("юшка", ["а", ""]),
    ("ишка", ["а", ""]),
    ("ишко", ["о", ""]),
    ("ышко", ["о", ""]),
    ("онка", ["а", "ка"]),
    ("енка", ["а", "ня"]),
    ("ьчик", [""]),
    ("ица", ["а"]),
    ("чка", ["ка"]),
    ("чик", [""]),
    ("ик", [""]),
    ("ок", [""]),
    ("ек", [""]),
    ("ец", [""]),
    ("ка", ["ь"]),
]
EN_DIM_RULES: list[tuple[str, list[str]]] = [
    ("ie", ["", "<dedouble>"]),
]

# Lexicalized words that match the rules but are not interchangeable diminutives.
DIM_EXCEPTIONS = {
    "ru": {"девушка", "бабушка", "дедушка", "аптечка", "песок", "замок", "точка",
           "ложка", "вилка", "белок", "кружка", "подушка", "игрушка", "бабочка",
           "курица", "площадка", "сетка", "клетка", "будка", "царица", "столица",
           "больница", "граница", "таблица", "улица", "пуговица", "гусеница",
           "дворец", "ручка", "внучка", "конец", "птенец",
           "мужик", "колокольчик", "лисица", "галочка", "истеричка", "упряжка",
           "девица"},
    "en": {"cookie", "movie", "genie", "pixie", "eerie", "collie"},
}


def _dim_bases(word: str, lang: str) -> list[str]:
    rules = RU_DIM_RULES if lang == "ru" else EN_DIM_RULES
    bases: list[str] = []
    for suffix, replacements in rules:
        if not word.endswith(suffix) or len(word) - len(suffix) < DIM_BASE_MIN_LEN:
            continue
        stem = word[: -len(suffix)]
        for repl in replacements:
            if repl == "<dedouble>":
                if len(stem) >= 2 and stem[-1] == stem[-2]:
                    bases.append(stem[:-1])
            else:
                bases.append(stem + repl)
    return bases


def filter_diminutives(
    words: list[str], matrix: np.ndarray, lang: str
) -> tuple[list[str], np.ndarray, list[tuple[str, str, float]]]:
    """matrix must be L2-normalized float32; words are frequency-ordered."""
    index = {w: i for i, w in enumerate(words)}
    exceptions = DIM_EXCEPTIONS[lang]
    keep: list[int] = []
    removed: list[tuple[str, str, float]] = []
    for i, w in enumerate(words):
        hit = None
        # -чик/-щик on an animate noun is an agent suffix (переводчик, заказчик),
        # not a diminutive — only inanimate -чик words (стаканчик) get cut.
        is_agent = (
            lang == "ru"
            and w.endswith(("чик", "щик"))
            and any("NOUN" in p.tag and "anim" in p.tag for p in _morph.parse(w))
        )
        if w not in exceptions and not is_agent:
            for base in _dim_bases(w, lang):
                j = index.get(base)
                if j is None or j >= i:  # base must be a more frequent existing word
                    continue
                cos = float(matrix[i] @ matrix[j])
                if cos >= DIM_COSINE_MIN:
                    hit = (w, base, cos)
                    break
        if hit:
            removed.append(hit)
        else:
            keep.append(i)
    return [words[i] for i in keep], matrix[keep], removed


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
    matrix = matrix / norms

    words, matrix, removed = filter_diminutives(words, matrix, args.lang)
    print(f"[{args.lang}] diminutive pass removed {len(removed)} words")

    DATA.mkdir(parents=True, exist_ok=True)
    with open(DATA / f"diminutives_removed_{args.lang}.txt", "w", encoding="utf-8") as f:
        f.writelines(f"{w}\t{base}\t{cos:.3f}\n" for w, base, cos in removed)
    np.save(DATA / f"vectors_{args.lang}.npy", matrix.astype(np.float16))
    with open(DATA / f"vocab_{args.lang}.txt", "w", encoding="utf-8") as f:
        f.write("\n".join(words) + "\n")

    print(f"[{args.lang}] done: {len(words)} words -> vectors_{args.lang}.npy / vocab_{args.lang}.txt")


if __name__ == "__main__":
    main()
