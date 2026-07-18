"""Build en_forms.json: inflected form -> lemma, for runtime lookup (docs/DATA_PIPELINE.md §6).

Collisions resolve in favor of the more frequent lemma, i.e. whichever word we see
first while iterating vocab_en.txt (already frequency-ordered).
"""

import json

from lemminflect import getAllInflections

from common import DATA


def main() -> None:
    vocab = (DATA / "vocab_en.txt").read_text(encoding="utf-8").splitlines()

    forms: dict[str, str] = {}
    for word in vocab:
        forms.setdefault(word, word)
        inflections = getAllInflections(word, upos="NOUN")
        for surface_forms in inflections.values():
            for form in surface_forms:
                forms.setdefault(form, word)

    out_path = DATA / "en_forms.json"
    out_path.write_text(json.dumps(forms, ensure_ascii=False, indent=None), encoding="utf-8")
    print(f"{len(forms)} forms -> {out_path}")


if __name__ == "__main__":
    main()
