# generator

Офлайн-скрипты подготовки словарей и рангов. Не деплоится на сервер — тяжёлые зависимости (эмбеддинги, NLP-модели) живут только тут. Подробности — `docs/DATA_PIPELINE.md`.

## Прогон

```
uv sync
uv run python download_assets.py                 # Navec (RU) + fastText (EN) + блэклисты, ~4.5 GB, один раз
uv run python build_guess_dict.py --lang ru       # -> data/vectors_ru.npy, data/vocab_ru.txt
uv run python build_guess_dict.py --lang en       # -> data/vectors_en.npy, data/vocab_en.txt
uv run python build_answer_dict.py --lang ru      # -> data/answer_candidates_ru.txt (топ-2500)
uv run python build_answer_dict.py --lang en      # -> data/answer_candidates_en.txt
uv run python build_en_forms.py                   # -> data/en_forms.json
```

**Дальше — ручная работа (не пропускать, см. `docs/DATA_PIPELINE.md` §3, §5):**

1. Открой `data/answer_candidates_{ru,en}.txt`, вычеркни скучное/канцелярское/абстрактное, оставь 1000–1500 слов на язык.
2. `uv run python smoke_test.py --lang ru` (и `en`) — автогейт §5: у каждого answer-кандидата в топ-10 не должно быть блэклист-слов и однокоренных; нарушителей убрать из answer-словаря.
3. `uv run python generate_ranks.py` → `data/game_static.db` (100 дней × RU+EN, фикс-сид шаффл).
4. `uv run python validate.py <слово>` на тестовых словах из §5 (вода, автомобиль, любовь, компьютер, собака, музыка, война, деньги, море, хлеб / water, car, love, computer, dog, music, war, money, sea, bread) — глазами смотришь топ-50. Если мусор — правим фильтры в `build_guess_dict.py` и пересобираем.

`data/` не идёт в git (большие бинарники) — артефакты едут на сервер отдельно через `deploy/push_data.sh` (Этап 6).
