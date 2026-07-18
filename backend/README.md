# backend

FastAPI + aiogram 3, один asyncio-процесс. См. `docs/TECH_SPEC.md` в корне репозитория.

```
uv sync
uv run uvicorn app.main:app --reload
uv run pytest
uv run ruff check
```

## Деплой

Push в `main` с изменениями в `backend/**` собирает и катит образ на прод VPS автоматически (см. `docs/DEPLOY.md` Фаза 1, `.github/workflows/ci.yml`). Бот: `@teplee_game_bot`.
