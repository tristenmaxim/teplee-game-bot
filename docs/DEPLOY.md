# Deploy & CI/CD

**Два этапа деплоя** (см. `ROADMAP.md`): сначала бот-версия без Mini App — не нужен домен и HTTPS вообще, только Docker на VPS. Домен, Caddy и Cloudflare Pages появляются в «Фазе 2», когда стартует Mini App. Ниже — сначала Фаза 1 (✅ сделано и живёт в проде на `146.103.114.81`, бот `@teplee_game_bot`), затем Фаза 2 (на будущее, не делать раньше времени).

## Фаза 1 — деплой бота ✅ готово

### 1. Схема

```
git push main (backend/** изменился)
   → GitHub Actions: ruff + pytest
   → build linux/amd64 image (buildx) → push ghcr.io/tristenmaxim/teplee-backend
   → SSH на VPS: docker rm -f teplee-backend (если есть) && docker-compose pull && docker-compose up -d
```

Бот работает через long polling — HTTPS и домен ему не нужны вообще. API (`/api/state`, `/api/guess`...) используется только ботом *внутри процесса* (общая бизнес-логика, без HTTP-вызовов — см. CLAUDE.md), наружу не торчит.

### 2. Docker на VPS

`deploy/docker-compose.yml` в репо — эталон, лежит на сервере в `/opt/teplee/docker-compose.yml` (правишь → `scp` → `docker-compose up -d`; CI/CD трогает только образ, не этот файл):
```yaml
services:
  backend:
    image: ghcr.io/tristenmaxim/teplee-backend:latest
    container_name: teplee-backend
    restart: unless-stopped
    env_file: .env
    ports:
      - "127.0.0.1:8000:8000"  # loopback only — для healthcheck.sh, не публично
    volumes:
      - ./data:/data
    mem_limit: 300m
    logging: { driver: json-file, options: { max-size: "10m", max-file: "3" } }
```
Один сервис, никакого Caddy. Порт 8000 привязан только к `127.0.0.1` — снаружи недоступен, нужен исключительно для локального health-чека. Никаких `0.0.0.0`-портов наружу (кроме исходящих — long polling сам стучится к Telegram).

`.env` на сервере (не в git, лежит в `/opt/teplee/.env`): `BOT_TOKEN`, `ADMIN_ID` (для алертов health-чека), `DB_PATH=/data/game.db`, `STATIC_DB_PATH=/data/game_static.db`, `DATA_DIR=/data`, `TZ=Europe/Moscow`. Плюс временно (см. ниже) `GAME_EPOCH_DATE`.

⚠️ **`GAME_EPOCH_DATE`:** реальная дата запуска в `TECH_SPEC.md` — `2026-08-01`, но прод стартовал раньше для живого тестирования на знакомых — эпоха в `.env` выставлена на день фактического го-лайва, иначе `day_id` уходит в минус и игра ломается (`word_not_found` на всё). Свериться и решить (оставить/убрать) при финальном широком релизе.

`mem_limit: 300m` защищает соседние контейнеры (VPN, hh-monitor) от OOM — реальный запас памяти на сервере тесный (~470 МБ свободно до нашего контейнера из 961 МБ), проверено `docker stats`/`free -h` перед первым деплоем.

### 3. GitHub Actions

`.github/workflows/ci.yml`, job `deploy` (needs: `backend`, только push в `main` с изменениями в `backend/**`):
```yaml
  deploy:
    needs: backend
    if: needs.backend.outputs.changed == 'true' && github.event_name == 'push' && github.ref == 'refs/heads/main'
    steps:
      - docker/login-action: ghcr.io, username tristenmaxim, password ${{ secrets.GHCR_TOKEN }}
      - docker/build-push-action: platforms linux/amd64, push, tags latest + ${{ github.sha }}
      - appleboy/ssh-action:
          script: |
            cd /opt/teplee
            docker-compose pull backend
            docker rm -f teplee-backend 2>/dev/null || true
            docker-compose up -d
            docker image prune -f
```
Job `webapp` (build + Cloudflare Pages) не создаём до Фазы 2 — нечего деплоить.

⚠️ **Два нюанса, найденных живьём на первом прогоне:**
- **`GHCR_TOKEN`, не `GITHUB_TOKEN`.** Пакет `teplee-backend` был создан вручную (личный токен) до появления воркфлоу и не привязан к этому репозиторию — `GITHUB_TOKEN` получает 403 при пуше. Секрет `GHCR_TOKEN` — тот же личный `gh auth token`, что и при ручном пуше; шире, чем хотелось бы (там же scope `repo`/`workflow`), но deploy-job гейтится только пушем в `main` (не PR/форки), так что риск утечки в чужой workflow отсутствует.
- **`docker-compose` v1 (единственная версия на VPS, `docker compose` v2-плагина нет и его нет в apt без добавления репозитория Docker) не умеет пересоздавать контейнеры из образов, собранных buildx/BuildKit** (`KeyError: 'ContainerConfig'`). Обход — явный `docker rm -f` перед `up -d`, зашит в шаг деплоя.

**GitHub Secrets:** `SSH_HOST`, `SSH_USER`, `SSH_KEY` (отдельный ed25519 deploy-ключ, добавлен в `authorized_keys` рядом с личным — не заменяет его), `GHCR_TOKEN`.

✅ Пароль root в открытом виде в рабочих заметках — используется вручную при уточняющих правках; для CI/CD заведён отдельный SSH-ключ, ничего секретного в workflow не передаётся паролем.

### 4. Данные

Артефакты генератора (сотни MB) **не идут через git**. Пока переносятся руками: `scp generator/data/{game_static.db,en_forms.json} root@<vps>:/opt/teplee/data/` + `docker rm -f teplee-backend && docker-compose up -d` на сервере. `deploy/push_data.sh` как отдельный скрипт — появится при следующем обновлении словарей (сейчас разница между «руками через scp» и «скриптом» непринципиальна при разовом переносе).

### 5. Бэкапы и мониторинг ✅ настроено

- `deploy/backup.sh` (лежит и на сервере в `/opt/teplee/backup.sh`) — cron `0 3 * * *`: `sqlite3 .backup` в `/opt/teplee/data/backup/game-<date>.db`, хранит последние 7.
- `deploy/healthcheck.sh` — cron `*/5 * * * *`: curl `127.0.0.1:8000/api/health` (порт проброшен только на loopback, см. §2); при неудаче шлёт сообщение на `ADMIN_ID` тем же ботом через Telegram Bot API напрямую (не зависит от того, жив ли сам процесс).
- `docker stats` после деплоя: RSS backend ~200–220 MB, укладывается в `mem_limit: 300m` с запасом.

### 6. Rollback

Образы тегируются sha → на VPS `docker-compose.yml` можно временно указать `image: ghcr.io/tristenmaxim/teplee-backend:<sha>` вместо `:latest`, затем `docker rm -f teplee-backend && docker-compose up -d`. Достаточно для проекта такого размера.

---

## Фаза 2 — добавление Mini App (позже, не сейчас)

Стартует, когда Mini App готов и нужен публичный HTTPS API + статика (см. ROADMAP «Потом»).

### HTTPS для API — обязательное решение

Mini App (HTTPS-страница на pages.dev) не может обращаться к `http://IP:8000` — браузер заблокирует (mixed content). Два варианта:

**Вариант A (рекомендую): дешёвый домен + Caddy.** Домен ~$2–10/год (например .ru/.online/.xyz). A-запись на VPS. Caddy-контейнер: авто-Let's Encrypt, две строки конфига:
```
api.твойдомен.ru {
    reverse_proxy backend:8000
}
```

**Вариант B (бесплатно): Cloudflare Tunnel.** Контейнер `cloudflared` → API доступен на `*.trycloudflare.com` (нестабильные URL) или через бесплатный домен в CF. Минус: ещё одна зависимость. Если не хочется тратить $5 — рабочий путь.

Добавляется в compose как ещё один сервис (`caddy`) рядом с `backend`. Заодно стоит сменить порт-биндинг backend с `127.0.0.1:8000:8000` на публикацию только через Caddy (backend вообще без `ports:`, Caddy достаёт его по внутренней docker-сети).

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
