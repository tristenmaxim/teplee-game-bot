# Deploy & CI/CD

**Два этапа деплоя** (см. `ROADMAP.md`): сначала бот-версия без Mini App — не нужен домен и HTTPS вообще, только Docker на VPS. Домен, Caddy и Cloudflare Pages появляются во «Фазе 2», когда стартует Mini App (Этап 8 роадмапа). Ниже — сначала Фаза 1 (актуальная сейчас), затем Фаза 2 (на будущее, не делать раньше времени).

## Фаза 1 — деплой бота (сейчас)

### 1. Схема

```
git push main
   → GitHub Actions: pytest → build backend image → push ghcr.io
   → SSH на VPS: docker compose pull && docker compose up -d
```

Бот работает через long polling — HTTPS и домен ему не нужны вообще. API (`/api/state`, `/api/guess`...) в этой фазе используется только ботом *внутри процесса* (общая бизнес-логика, без HTTP-вызовов — см. CLAUDE.md), наружу не торчит и Caddy ему не нужен.

### 2. Docker на VPS

`/opt/teplee/docker-compose.yml`:
```yaml
services:
  backend:
    image: ghcr.io/<you>/teplee-backend:latest
    restart: unless-stopped
    env_file: .env
    volumes:
      - ./data:/data          # game.db, game_static.db, vectors, en_forms.json
    mem_limit: 400m
    logging: { driver: json-file, options: { max-size: "10m", max-file: "3" } }
```
Один сервис, никакого Caddy, никаких открытых портов наружу (кроме исходящих — long polling сам стучится к Telegram).

`.env` на сервере (не в git): `BOT_TOKEN`, `ADMIN_ID`, `DB_PATH=/data/game.db`, `STATIC_DB_PATH=/data/game_static.db`, `DATA_DIR=/data`, `TZ=Europe/Moscow`. `WEBAPP_URL`/`API_PUBLIC_URL` пока не нужны — не заданы, Mini App ещё не собирается.

`mem_limit` защищает соседние контейнеры (ВПН, алерт-бот) от OOM.

### 3. GitHub Actions

`.github/workflows/deploy.yml` (суть):
```yaml
on: { push: { branches: [main] } }
jobs:
  test:
    runs-on: ubuntu-latest
    steps: [checkout, setup python, uv sync, ruff check, pytest]
  backend:
    needs: test
    if: # изменения в backend/**
    steps:
      - docker/build-push-action → ghcr.io/<you>/teplee-backend:latest + :${{ github.sha }}
      - appleboy/ssh-action:
          script: cd /opt/teplee && docker compose pull && docker compose up -d && docker image prune -f
```
Job `webapp` (build + Cloudflare Pages) не создаём до Фазы 2 — нечего деплоить.

**GitHub Secrets:** `SSH_HOST`, `SSH_USER`, `SSH_KEY` (отдельный deploy-ключ, не личный), `GHCR` — через `GITHUB_TOKEN`.

⚠️ Перед первым деплоем: сменить пароль root на VPS и перейти на SSH-ключи (текущий доступ — пароль в открытом виде в рабочих заметках, для CI/CD нужен выделенный deploy-ключ, не личный пароль).

### 4. Данные

Артефакты генератора (сотни MB) **не идут через git**. Скрипт `deploy/push_data.sh`: `rsync -avz game_static.db vectors_* en_forms.json user@vps:/opt/teplee/data/` + перезапуск backend. Запускается вручную при обновлении словарей/дней.

### 5. Бэкапы и мониторинг

- Cron на VPS: ночью `sqlite3 /data/game.db ".backup /data/backup/game-$(date +%F).db"` + хранить 7 шт. (runtime-данные; статика восстанавливается генератором).
- Health: без публичного домена `/api/health` не торчит наружу — проверяем локально на VPS: cron `curl -sf localhost:8000/api/health || <alert>`, либо через существующий алерт-бот по SSH/внутренней сети. Backend шлёт необработанные исключения в `ADMIN_ID`.
- `docker stats` глазами после запуска: убедиться, что RSS backend < 350 MB.

### 6. Rollback

Образы тегируются sha → `docker compose` с конкретным тегом: на VPS `IMAGE_TAG=<sha> docker compose up -d` (тег через env в compose). Достаточно для проекта такого размера.

---

## Фаза 2 — добавление Mini App (позже, не сейчас)

Стартует вместе с Этапом 8 роадмапа, когда Mini App готов и нужен публичный HTTPS API + статика.

### HTTPS для API — обязательное решение

Mini App (HTTPS-страница на pages.dev) не может обращаться к `http://IP:8000` — браузер заблокирует (mixed content). Два варианта:

**Вариант A (рекомендую): дешёвый домен + Caddy.** Домен ~$2–10/год (например .ru/.online/.xyz). A-запись на VPS. Caddy-контейнер: авто-Let's Encrypt, две строки конфига:
```
api.твойдомен.ru {
    reverse_proxy backend:8000
}
```

**Вариант B (бесплатно): Cloudflare Tunnel.** Контейнер `cloudflared` → API доступен на `*.trycloudflare.com` (нестабильные URL) или через бесплатный домен в CF. Минус: ещё одна зависимость. Если не хочется тратить $5 — рабочий путь.

Добавляется в compose как ещё один сервис (`caddy`) рядом с `backend`, без изменений в самом backend-контейнере.

### Webapp job в CI

```yaml
  webapp:
    needs: test
    if: # изменения в webapp/**
    steps:
      - npm ci && npm run build   # VITE_API_URL из secrets
      - cloudflare/wrangler-action: pages deploy webapp/dist --project-name=teplee
```
**Доп. secrets:** `CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_ACCOUNT_ID`, `VITE_API_URL`.

Path-фильтры (`dorny/paths-filter` или `paths:`) — чтобы пуш только фронта не передеплоивал бэкенд, и наоборот.
