# backend

FastAPI + aiogram 3, один asyncio-процесс. См. `docs/TECH_SPEC.md` в корне репозитория.

```
uv sync
uv run uvicorn app.main:app --reload
uv run pytest
uv run ruff check
```
