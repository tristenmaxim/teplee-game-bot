"""Download embedding models and profanity blacklists into data/ (idempotent)."""

import zipfile
from pathlib import Path

import requests
from tqdm import tqdm

DATA = Path(__file__).parent / "data"
MODELS = DATA / "models"

NAVEC_URL = "https://storage.yandexcloud.net/natasha-navec/packs/navec_hudlit_v1_12B_500K_300d_100q.tar"
FASTTEXT_ZIP_URL = "https://dl.fbaipublicfiles.com/fasttext/vectors-english/crawl-300d-2M.vec.zip"
BLACKLIST_BASE = (
    "https://raw.githubusercontent.com/LDNOOBW/"
    "List-of-Dirty-Naughty-Obscene-and-Otherwise-Bad-Words/master"
)


def download(url: str, dest: Path) -> None:
    if dest.exists():
        print(f"skip (exists): {dest.name}")
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    resp = requests.get(url, stream=True, timeout=30)
    resp.raise_for_status()
    total = int(resp.headers.get("content-length", 0))
    with open(tmp, "wb") as f, tqdm(total=total, unit="B", unit_scale=True, desc=dest.name) as bar:
        for chunk in resp.iter_content(chunk_size=1 << 20):
            f.write(chunk)
            bar.update(len(chunk))
    tmp.rename(dest)


def main() -> None:
    download(NAVEC_URL, MODELS / "navec_hudlit_v1_12B_500K_300d_100q.tar")

    ft_zip = MODELS / "crawl-300d-2M.vec.zip"
    download(FASTTEXT_ZIP_URL, ft_zip)

    ft_vec = MODELS / "crawl-300d-2M.vec"
    if not ft_vec.exists():
        print("unzipping fastText vectors...")
        with zipfile.ZipFile(ft_zip) as zf:
            zf.extract("crawl-300d-2M.vec", MODELS)

    for lang in ("ru", "en"):
        download(f"{BLACKLIST_BASE}/{lang}", DATA / f"blacklist_{lang}.txt")

    print("done.")


if __name__ == "__main__":
    main()
