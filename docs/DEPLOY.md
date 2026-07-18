# Deploy & CI/CD

## 1. Схема

```
git push main
   → GitHub Actions: pytest → build backend image → push ghcr.io
   → SSH на VPS: docker compose pull && docker compose up -d
   → webapp: build → deploy Cloudflare Pages (wrangler-action)
```

## 2. HTTPS для API — обязательное решение

Mini App (HTTPS-страница на pages.dev) не может обращаться к `http://IP:8000` — браузер заблокирует (mixed content). Два варианта:

**Вариант A (рекомендую): дешёвый домен + Caddy.** Домен ~$2–10/год (например .ru/.online/.xyz). A-запись на VPS. Caddy-контейнер: авто-Let's Encrypt, две строки конфига:
```
api.твойдомен.ru {
    reverse_proxy backend:8000
}
```

**Вариант B (бесплатно): Cloudflare Tunnel.** Контейнер `cloudflared` → API доступен на `*.trycloudflare.com` (нестабильные URL) или через бесплатный домен в CF. Минус: ещё одна зависимость. Если не хочется тратить $5 — рабочий путь.

Бот работает через long polling — ему домен не нужен вообще.

## 3. Docker на VPS

`/opt/ugadaika/docker-compose.yml`:
```yaml
services:
  backend:
    image: ghcr.io/<you>/ugadaika-backend:latest
    restart: unless-stopped
    env_file: .env
    volumes:
      - ./data:/data          # game.db, game_static.db, vectors, en_forms.json
    mem_limit: 400m
    logging: { driver: json-file, options: { max-size: "10m", max-file: "3" } }
  caddy:
    image: caddy:2-alpine
    restart: unless-stopped
    ports: ["80:80", "443:443"]
    volumes:
      - ./Caddyfile:/etc/caddy/Caddyfile
      - caddy_data:/data
volumes:
  caddy_data:
```
`.env` на сервере (не в git): `BOT_TOKEN`, `WEBAPP_URL`, `ADMIN_ID`, `DB_PATH=/data/game.db`, `TZ=Europe/Moscow`.

`mem_limit` защищает соседние контейнеры (ВПН, алерт-бот) от OOM.

## 4. GitHub Actions

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
      - docker/build-push-action → ghcr.io/<you>/ugadaika-backend:latest + :${{ github.sha }}
      - appleboy/ssh-action:
          script: cd /opt/ugadaika && docker compose pull && docker compose up -d && docker image prune -f
  webapp:
    needs: test
    if: # изменения в webapp/**
    steps:
      - npm ci && npm run build   # VITE_API_URL из secrets
      - cloudflare/wrangler-action: pages deploy webapp/dist --project-name=ugadaika
```

**GitHub Secrets:** `SSH_HOST`, `SSH_USER`, `SSH_KEY` (отдельный deploy-ключ, не личный), `GHCR` — через `GITHUB_TOKEN`, `CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_ACCOUNT_ID`, `VITE_API_URL`.

Path-фильтры (`dorny/paths-filter` или `paths:`) — чтобы пуш только фронта не передеплоивал бэкенд.

## 5. Данные

Артефакты генератора (сотни MB) **не идут через git**. Скрипт `deploy/push_data.sh`: `rsync -avz game_static.db vectors_* en_forms.json user@vps:/opt/ugadaika/data/` + перезапуск backend. Запускается вручную при обновлении словарей/дней.

## 6. Бэкапы и мониторинг

- Cron на VPS: ночью `sqlite3 /data/game.db ".backup /data/backup/game-$(date +%F).db"` + хранить 7 шт. (runtime-данные; статика восстанавливается генератором).
- Health: твой существующий алерт-бот curl-ит `/api/health` раз в минуту → алерт при падении. Backend шлёт необработанные исключения в `ADMIN_ID`.
- `docker stats` глазами после запуска: убедиться, что RSS backend < 350 MB.

## 7. Rollback

Образы тегируются sha → `docker compose` с конкретным тегом: на VPS `IMAGE_TAG=<sha> docker compose up -d` (тег через env в compose). Достаточно для проекта такого размера.
