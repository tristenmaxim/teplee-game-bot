# CLAUDE.md — «Теплее!»

Telegram-игра: ежедневная семантическая головоломка (стиль Contexto) + челленджи «загадай слово другу». RU-интерфейс, слова RU и EN. Полная документация: `docs/PRD.md`, `docs/TECH_SPEC.md`, `docs/DATA_PIPELINE.md`, `docs/ROADMAP.md`, `docs/DEPLOY.md` — **читай релевантный док перед задачей.**

## Структура

```
backend/    Python 3.12: FastAPI + aiogram 3 в одном asyncio-процессе. uv, ruff, pytest.
webapp/     React 18 + Vite + TypeScript + Tailwind. Telegram Mini App.
generator/  Офлайн-скрипты словарей/рангов. Не деплоится. Тяжёлые зависимости только тут.
deploy/     docker-compose, Caddyfile, push_data.sh
```

## Жёсткие ограничения (не нарушать)

- Сервер: 1 CPU / 1 GB RAM, на нём чужие контейнеры. **Никаких ML-моделей, spaCy, NLTK, torch в backend.** Только pymorphy3, numpy (матрица векторов), aiosqlite.
- Бот — **long polling**, не webhook.
- Ответ бота на попытку — **editMessageText** одного игрового сообщения, не новые сообщения.
- SQLite: WAL, одно соединение на запись, `busy_timeout=5000`. Статические таблицы — отдельный файл `game_static.db` через `ATTACH` (read-only).
- API-auth: только через валидацию Telegram `initData` (HMAC от BOT_TOKEN). Никогда не доверять `telegram_id` из тела запроса.
- Секреты — только env (`BOT_TOKEN` и пр.), в git не коммитить.
- Время/day_id — Europe/Moscow. `day_id = (msk_date - EPOCH_DATE).days`.

## Доменные правила

- Ранг 1 = победа. Цвета: ≤100 🟩, ≤1000 🟨, иначе ⬜.
- Лемматизация перед поиском: RU — pymorphy3 normal_form; EN — lookup в `en_forms.json`; всегда lowercase, ё→е.
- Повтор слова — не ошибка (вернуть существующий ранг, `is_new: false`).
- `game_key`: `d:<day_id>:<lang>` (daily) | `c:<challenge_id>` (челлендж).
- Слово челленджа обязано быть в guess-словаре; наружу никогда не отдаётся.

## Стиль

- Код и комментарии — English; тексты для пользователей (бот, Mini App) — русские, тон лёгкий, с эмодзи по PRD.
- Type hints везде; pydantic-модели для API; ruff clean.
- Бизнес-логика — в `backend/app/services/` (общая для бота и API, без HTTP-прослойки между ними).
- Тесты на каждую фичу движка (лемматизация, guess, стрики, initData). Запуск: `uv run pytest`.
- Коммиты — маленькие, работающие инкременты. Conventional commits (feat:, fix:).

## Команды

```
backend:  uv sync · uv run uvicorn app.main:app --reload · uv run pytest · uv run ruff check
webapp:   npm ci · npm run dev · npm run build
local:    docker compose up  (из корня, dev-режим)
```
