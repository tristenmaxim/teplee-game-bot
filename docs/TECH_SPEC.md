# Tech Spec — «Теплее!»

## 1. Архитектура

Ограничения сервера: **1 CPU / 1 GB RAM / 10 GB HDD**, на нём уже крутятся другие контейнеры. Принцип: **тяжёлые вычисления — офлайн, сервер — тонкий**.

```
[Локальный ПК] generator/  →  game.db + vectors_ru.npy + vectors_en.npy
                                      │ (кладутся на сервер при деплое данных)
                                      ▼
[VPS, Docker]  backend: FastAPI (REST) + aiogram 3 (long polling) — один процесс/контейнер
                  │ SQLite (WAL)
                  ▼
[Cloudflare Pages]  webapp: React Mini App  → HTTPS → API
```

- **generator/** — офлайн-скрипты (см. `DATA_PIPELINE.md`). Модели эмбеддингов живут только здесь.
- **backend/** — FastAPI + aiogram в одном asyncio-процессе (общий event loop, общий доступ к БД). Никакого ML: SQL-запросы + лемматизация + numpy dot-product для кастомных челленджей.
- **webapp/** — статика на Cloudflare Pages (бесплатно, HTTPS из коробки).

### Почему polling, а не webhook
Бот через long polling не требует входящего HTTPS → домен нужен только для API (Mini App обязан ходить по HTTPS). Меньше движущихся частей.

**v1 (сейчас, см. ROADMAP):** Mini App и домен/HTTPS для API откладываются — деплоится только backend-контейнер с ботом, API используется им напрямую (без HTTP-прослойки), наружу не торчит.

### Память (бюджет 1 GB, из которого часть занята соседями)
- Python + FastAPI + aiogram: ~120–180 MB
- pymorphy3 словари: ~30 MB
- Матрицы векторов guess-словаря: 40k слов × 300 dim × float16 ≈ 24 MB × 2 языка ≈ 50 MB (mmap — можно и меньше в RSS)
- SQLite: страничный кэш, настраиваем `PRAGMA cache_size` скромно.
- Итого ~250–300 MB — влезает. Если нет — апгрейд VPS (владелец готов).

## 2. Стек

| Слой | Технология |
|---|---|
| Backend | Python 3.12, FastAPI, aiogram 3.x, uvicorn, aiosqlite |
| NLP на сервере | pymorphy3 (RU-лемматизация), простой EN-лемматизатор (lemminflect или словарь форм, собранный офлайн — предпочтительно второе, см. §5) |
| Числа | numpy (только для челленджей) |
| БД | SQLite, WAL mode |
| Frontend | React 18 + Vite + TypeScript, Tailwind, @telegram-apps/sdk (или window.Telegram.WebApp напрямую) |
| Инфра | Docker + docker compose, GitHub Actions, Caddy (HTTPS) или Cloudflare Tunnel |

## 3. Схема БД (SQLite, файл `data/game.db`)

`PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL; PRAGMA busy_timeout=5000;`
Все записи — через одно соединение (aiosqlite) в одном процессе → блокировки не проблема на наших нагрузках.

```sql
-- Сгенерировано офлайн (генератор), read-only для сервера
CREATE TABLE words_rank (
  day_id  INTEGER NOT NULL,
  lang    TEXT    NOT NULL CHECK(lang IN ('ru','en')),
  word    TEXT    NOT NULL,          -- нормальная форма, lowercase
  rank    INTEGER NOT NULL,          -- 1 = слово дня
  PRIMARY KEY (day_id, lang, word)
) WITHOUT ROWID;

CREATE TABLE daily_words (            -- ответы по дням (для пуша «вчера было…»)
  day_id INTEGER NOT NULL,
  lang   TEXT NOT NULL,
  word   TEXT NOT NULL,
  PRIMARY KEY (day_id, lang)
);

-- Runtime-таблицы (создаёт сервер при первом старте, migrations простые .sql)
CREATE TABLE users (
  telegram_id  INTEGER PRIMARY KEY,
  username     TEXT,
  first_name   TEXT,
  lang_mode    TEXT DEFAULT 'ru',
  notifications INTEGER DEFAULT 1,
  game_message_id INTEGER,           -- id закреплённого игрового сообщения в ЛС
  streak       INTEGER DEFAULT 0,
  last_win_day INTEGER,
  referred_by  TEXT,                 -- 'c_<id>' | 'share' | NULL — источник прихода
  created_at   TEXT DEFAULT (datetime('now'))
);

CREATE TABLE attempts (
  telegram_id INTEGER NOT NULL,
  game_key    TEXT    NOT NULL,      -- 'd:<day_id>:<lang>' или 'c:<challenge_id>'
  word        TEXT    NOT NULL,      -- нормальная форма
  rank        INTEGER NOT NULL,
  created_at  TEXT DEFAULT (datetime('now')),
  PRIMARY KEY (telegram_id, game_key, word)
);
CREATE INDEX idx_attempts ON attempts(telegram_id, game_key);

CREATE TABLE challenges (
  id          TEXT PRIMARY KEY,      -- 8 символов base62, генерится secrets
  creator_id  INTEGER NOT NULL,
  lang        TEXT NOT NULL,
  word        TEXT NOT NULL,         -- секрет, наружу не отдаётся
  created_at  TEXT DEFAULT (datetime('now')),
  expires_at  TEXT NOT NULL
);

CREATE TABLE challenge_rank (         -- предвычисленные ранги для кастомного слова
  challenge_id TEXT NOT NULL,
  word         TEXT NOT NULL,
  rank         INTEGER NOT NULL,
  PRIMARY KEY (challenge_id, word)
) WITHOUT ROWID;

CREATE TABLE challenge_results (      -- победы (для таблицы «кто и за сколько»)
  challenge_id TEXT NOT NULL,
  telegram_id  INTEGER NOT NULL,
  attempts     INTEGER NOT NULL,
  won_at       TEXT DEFAULT (datetime('now')),
  PRIMARY KEY (challenge_id, telegram_id)
);
```

`day_id` = `(now_msk.date() - date(2026, 8, 1)).days` — целое от даты запуска; вся логика оперирует МСК.

### Размер
100 дней × 2 языка × 40k слов ≈ 8M строк `words_rank` ≈ 250–400 MB. Ок для 10 GB. Раз в ~3 месяца доливать новые дни (скрипт деплоя данных).

## 4. API (FastAPI, префикс `/api`)

### Аутентификация
Каждый запрос Mini App несёт заголовок `Authorization: tma <initDataRaw>`. Сервер валидирует подпись HMAC-SHA256 ключом из `BOT_TOKEN` (стандартный алгоритм Telegram), извлекает `user.id`. **`telegram_id` из тела/квери никогда не принимается на веру.** Невалидная подпись или initData старше 24ч → 401.

### Эндпоинты

`GET /api/state?game=d` | `?game=c_<id>`
→ текущее игровое состояние пользователя:
```json
{
  "game_key": "d:42:ru", "day_no": 42, "lang": "ru",
  "attempts": [{"word":"собака","rank":14},{"word":"лес","rank":610}],
  "solved": false, "attempts_count": 24, "streak": 5
}
```

`POST /api/guess`  body `{"game": "d" | "c_<id>", "word": "котами"}`
1. Определить `game_key` (для `d` — по текущему `day_id` и `lang_mode` юзера; язык можно переопределить полем `lang`).
2. Лемматизировать: RU → pymorphy3 `normal_form`; EN → словарь форм (см. §5). Lowercase, ё→е.
3. Найти ранг в `words_rank` / `challenge_rank`. Нет → `409 {"error":"word_not_found"}`.
4. UPSERT в `attempts` (повтор — не ошибка, вернуть existing).
5. Если rank == 1: обновить streak (daily) или записать `challenge_results` + уведомить создателя.
→ `{"word":"кот","rank":15,"is_new":true,"is_win":false}`

`POST /api/lang`  body `{"lang":"en"}` — сменить режим.

`POST /api/challenge`  body `{"word":"космос","lang":"ru"}`
1. Лемматизировать, проверить наличие в guess-словаре (векторной матрице).
2. Сгенерить `id`, посчитать cosine similarity слова против всей матрицы (numpy, <1 сек), записать 40k строк в `challenge_rank` одной транзакцией (executemany, ~1–2 сек — приемлемо, показать «⏳ Готовлю челлендж…»).
3. → `{"id":"aB3xK9qZ","link":"https://t.me/<bot>?start=c_aB3xK9qZ"}`

`GET /api/challenge/<id>` — мета (создатель, язык, жив ли, таблица результатов; слово не отдаётся).
`GET /api/my/challenges` — мои челленджи + результаты.
`GET /api/stats` — попытки/победы/стрик.

Rate limit: 5 guess/сек на юзера (in-memory token bucket) — от скриптеров.

## 5. Лемматизация EN без тяжёлых библиотек

NLTK/spaCy на сервере не нужны. Офлайн-генератор собирает **словарь форм**: для каждого слова guess-словаря — его формы (множественное число и пр.) через lemminflect/NLTK локально → таблица/JSON `en_forms {form → lemma}` (~100k строк, грузится в dict, ~10 MB). Сервер делает lookup. Не нашли форму → пробуем слово как есть.

## 6. Бот (aiogram 3)

### Игровое сообщение
- У каждого юзера в ЛС — одно «игровое сообщение» (`users.game_message_id`). Ответ на любую попытку = `editMessageText` этого сообщения (контент из PRD §5A) + inline-кнопки: `WebAppInfo`-кнопка «🎮 Открыть игру», «🎯 Загадать другу», «🇷🇺/🇬🇧».
- Если edit падает (сообщение удалено юзером / >48ч / message is not modified) → отправить новое и сохранить id.
- Троттлинг edit: не чаще 1 раза в секунду на чат (Telegram limit), очередь per-user.

### Роутинг
- `/start` → onboarding, создать users-запись, отправить игровое сообщение.
- `/start c_<id>` → загрузить челлендж, `referred_by` для нового юзера, режим челленджа.
- Любой текст не-команда → guess во «внутренний сервис» (та же функция, что у API, без HTTP-прослойки).
- Активная игра юзера (daily vs челлендж) хранится в поле state (простая колонка `active_game` в users, без FSM-хранилищ).
- `/lang`, `/stats`, `/mute`, `/help`.
- Ошибка «нет слова» → отдельное сообщение, `asyncio.create_task` удаляет через 3 сек.

### Победа в челлендже
Уведомление создателю (`send_message`), обёрнуто в try/except (мог заблокировать бота).

## 7. Mini App (React + Vite + TS) — реализация отложена до v1.5, см. ROADMAP

- Инициализация: `WebApp.ready(); WebApp.expand();` цвета из `themeParams` → CSS-переменные.
- Стейт: React Query (или простой fetch + useState). При старте `GET /api/state`, дальше оптимистичные апдейты после `POST /guess`.
- UI: шапка (день, язык-переключатель, счётчик, стрик) · лента попыток, sort by rank asc, последняя попытка подсвечена и продублирована сверху ленты отдельной строкой «последнее» · инпут fixed bottom, disable на время запроса.
- Цвет плашки: rank ≤ 100 зелёная, ≤ 1000 жёлтая, иначе серая; плюс градиент-прогресс внутри плашки (чем ближе, тем длиннее заливка — как в Contexto).
- Haptics: `impactOccurred('light')` при ответе, `notificationOccurred('success')` при 🟩, `('error')` + shake при word_not_found.
- Победа: конфетти (canvas-confetti), модалка со статистикой, кнопка Share → `WebApp.openTelegramLink('https://t.me/share/url?...')`.
- Вкладка «Челленджи»: создать (инпут слова + язык), список моих с результатами, кнопка «Скопировать ссылку».
- Deep link в челлендж: `startapp`-параметр → открытие Mini App сразу в игре челленджа.

## 8. Cron / рассылка

- Внутри backend-процесса — apscheduler: job в 09:00 МСК.
- `SELECT telegram_id, lang_mode FROM users WHERE notifications=1` → рассылка чанками ≤ 25 msg/сек, обработка `RetryAfter`, `Forbidden` (пометить notifications=0).
- Текст: «🌅 Слово дня #43 уже ждёт! Вчера было: МОЛОКО» (вчерашнее слово из `daily_words` по lang_mode юзера).

## 9. Конфигурация (env)

`BOT_TOKEN`, `WEBAPP_URL` (pages.dev), `API_PUBLIC_URL`, `DB_PATH=/data/game.db`, `VECTORS_DIR=/data`, `TZ=Europe/Moscow`, `ADMIN_ID` (для /admin-статистики и алертов об ошибках).

## 10. Тесты

- Юнит: лемматизация (таблица кейсов RU/EN, ё/е, регистр), day_id, подсчёт стрика, валидация initData (готовые фикстуры подписи).
- Интеграционные: /guess happy path, повтор слова, word_not_found, победа, создание челленджа и победа в нём.
- Запуск в CI перед деплоем.
