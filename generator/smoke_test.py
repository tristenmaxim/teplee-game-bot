"""Automated smoke test for answer candidates (docs/DATA_PIPELINE.md §5).

For every word in answer_candidates_<lang>.txt, check its top-10 nearest guess-dict
neighbors for (a) blacklist words and (b) same-root suffix variants of the answer
("собака" with "собачий"/"собаковод" in the hot zone would frustrate players).

Usage: uv run python smoke_test.py --lang ru [--top 10]
Exits non-zero if any violations are found; prints them all.
"""

import argparse

import numpy as np

from common import DATA, load_blacklist

PREFIX_MIN = 4  # shared-prefix length that counts as "same root" for the suffix check


def same_root(answer: str, neighbor: str) -> bool:
    if neighbor.startswith(answer[:PREFIX_MIN]) and answer.startswith(neighbor[:PREFIX_MIN]):
        prefix = min(len(answer), len(neighbor))
        return answer[:prefix] == neighbor[:prefix]
    return False


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--lang", choices=["ru", "en"], required=True)
    parser.add_argument("--top", type=int, default=10)
    args = parser.parse_args()

    vectors = np.load(DATA / f"vectors_{args.lang}.npy").astype(np.float32)
    vocab = (DATA / f"vocab_{args.lang}.txt").read_text(encoding="utf-8").splitlines()
    index = {w: i for i, w in enumerate(vocab)}
    blacklist = load_blacklist(args.lang)
    answers = [
        w
        for w in (DATA / f"answer_candidates_{args.lang}.txt")
        .read_text(encoding="utf-8")
        .splitlines()
        if w
    ]

    violations = 0
    for answer in answers:
        i = index.get(answer)
        if i is None:
            print(f"MISSING  {answer}: not in guess dict")
            violations += 1
            continue
        sims = vectors @ vectors[i]
        top = np.argpartition(-sims, args.top + 1)[: args.top + 1]
        top = top[np.argsort(-sims[top])]
        for j in top:
            if j == i:
                continue
            neighbor = vocab[j]
            if neighbor in blacklist:
                print(f"BLACKLIST {answer}: '{neighbor}' in top-{args.top}")
                violations += 1
            elif same_root(answer, neighbor) and len(answer) >= PREFIX_MIN:
                print(f"SUFFIX    {answer}: '{neighbor}' (sim {sims[j]:.3f}) in top-{args.top}")
                violations += 1

    print(f"[{args.lang}] {len(answers)} answers checked, {violations} violations")
    raise SystemExit(1 if violations else 0)


if __name__ == "__main__":
    main()
