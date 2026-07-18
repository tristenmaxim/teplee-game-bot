"""Produce answer-dict candidates for manual review (docs/DATA_PIPELINE.md §3).

Takes the top-N most frequent words of the guess dictionary (already frequency-ordered
by build_guess_dict.py) and writes them one-per-line for hand curation: delete the
boring/bureaucratic/abstract ones, keep ~1000-1500 concrete, "fun to guess" nouns.
"""

import argparse

from common import DATA

TOP_N = 2500


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--lang", choices=["ru", "en"], required=True)
    parser.add_argument("--top-n", type=int, default=TOP_N)
    args = parser.parse_args()

    vocab_path = DATA / f"vocab_{args.lang}.txt"
    words = vocab_path.read_text(encoding="utf-8").splitlines()[: args.top_n]

    out_path = DATA / f"answer_candidates_{args.lang}.txt"
    out_path.write_text("\n".join(words) + "\n", encoding="utf-8")
    print(f"[{args.lang}] wrote {len(words)} candidates -> {out_path}")
    print("Отредактируй файл руками: удали скучные/канцелярские/абстрактные слова, оставь 1000-1500.")


if __name__ == "__main__":
    main()
