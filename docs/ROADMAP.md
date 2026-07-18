# Roadmap — 7 этапов под Claude Code

Правила работы: один этап = одна-две сессии Claude Code. Перед стартом этапа дай Claude Code прочитать `CLAUDE.md` + релевантный раздел доков. Этап закрыт только когда выполнены **критерии приёмки** и тесты зелёные. Коммит после каждого работающего инкремента.

---

## Этап 0 — Скелет репозитория (30 мин)

Monorepo:
```
/backend      # FastAPI + aiogram, pyproject.toml (uv), Dockerfile
/webapp       # React + Vite + TS + Tailwind
/generator    # офлайн-скрипты данных (не деплоится)
/deploy       # docker-compose.yml, Caddyfile, скрипты
/.github/workflows
CLAUDE.md
```
**Промпт:** «Создай скелет monorepo по CLAUDE.md: backend (FastAPI hello + healthcheck /api/health, uv, ruff, pytest), webapp (Vite React TS Tailwind, заглушка), generator (пустой пакет с README), docker-compose для локальной разработки».
**Приёмка:** `docker compose up` локально поднимает API, `curl /api/health` → 200; `npm run dev` открывает заглушку.

## Этап 1 — Данные (локально, руками + Claude Code) · 3–5 дней

По `DATA_PIPELINE.md`. Claude Code пишет скрипты, ты запускаешь и валидируешь глазами.
**Приёмка:** `game_static.db` на 100 дней RU+EN; `validate.py собака` и `validate.py dog` выдают чистый топ-50; артефакты векторов и `en_forms.json` собраны. ⚠️ Не переходить дальше, пока топы не выглядят хорошо.

## Этап 2 — Игровой движок + API · 2 дня

По `TECH_SPEC.md` §3–5: схема БД, ATTACH статической базы, лемматизация RU/EN, сервис `guess()`/`state()`, эндпоинты `/api/state`, `/api/guess`, `/api/lang`, `/api/stats`, валидация initData, rate limit.
**Приёмка:** pytest покрывает лемматизацию, guess (новое/повтор/не найдено/победа/стрик), initData (валидная и подделанная подпись). Ручной прогон через curl с тестовой initData.

## Этап 3 — Бот MVP · 2–3 дня

По `TECH_SPEC.md` §6: /start, onboarding, игровое сообщение с editMessageText, топ-5, /lang, /stats, /mute, обработка ошибок словаря (авто-удаление через 3с), победа + share-текст.
**Приёмка:** играбельно end-to-end в реальном Telegram с локально запущенным backend (polling работает без домена). В чате всегда одно игровое сообщение. Дать брату потестить. 🎯

## Этап 4 — Mini App · 3–4 дня

По `TECH_SPEC.md` §7: тема, лента, инпут, цвета/градиент, haptics, победа с конфетти, share, синхронизация с ботом (`/api/state`). Для локальной разработки — mock initData + vite dev; проверка в Telegram через временный туннель (cloudflared) или задеплоенный Pages-превью.
**Приёмка:** слово, введённое в чате бота, видно в Mini App и наоборот; тема тёмная/светлая корректна; haptics работают на телефоне.

## Этап 5 — Челленджи «Загадай другу» · 2–3 дня

API `POST /api/challenge`, расчёт рангов по матрице векторов, deep links `?start=c_*` и `?startapp=c_*`, флоу в боте и в Mini App, уведомление создателя, таблица результатов, `referred_by`.
**Приёмка:** полный цикл на двух аккаунтах (ты + брат): создал → переслал → друг угадал → тебе пришло уведомление → «загадать в ответ». Время создания челленджа ≤ 3 сек.

## Этап 6 — Деплой + CI/CD · 1–2 дня

По `DEPLOY.md`: Dockerfile prod, compose на VPS, Caddy/Tunnel HTTPS для API, Cloudflare Pages для webapp, GitHub Actions (test → build → push GHCR → SSH deploy; webapp → Pages). Перенос данных `push_data.sh`. apscheduler-пуш 09:00.
**Приёмка:** push в main → через ~3 мин прод обновлён; Mini App открывается с прода; пуш приходит; `/api/health` мониторится (uptime-kuma или cron-curl с алертом в твой алерт-бот).

## Этап 7 — Полировка + релиз · 2–3 дня

Shake-анимация, стрик-огонёк, экран победы, тексты онбординга, /help, красивый username бота, аватар, описание. Обкатка на 10–20 знакомых → фикс болячек → пост на VC/Habr/Reddit r/telegram + тематические чаты.
**Приёмка:** 3 дня без крашей на живых пользователях; метрики §7 PRD считаются (простой /admin-отчёт: DAU, новые, источники, победы).

---

**Итого:** ~2.5–3.5 недели плотной работы. Дуэли и лидерборды (v2) — отдельным циклом после первых метрик.
