# deploy

Прод-артефакты для VPS (Фаза 1 — бот без Mini App, см. `docs/DEPLOY.md`):

- `docker-compose.yml` — эталон того, что лежит на сервере в `/opt/teplee/docker-compose.yml`. Правишь тут → копируешь на сервер (`scp`) → `docker-compose up -d`. CI/CD (`.github/workflows/ci.yml`) пересобирает и катит только образ, сам файл не трогает.
- `backup.sh` — ночной бэкап `game.db` (cron `0 3 * * *` на сервере), хранит 7 последних.
- `healthcheck.sh` — раз в 5 минут (cron `*/5 * * * *`) проверяет `localhost:8000/api/health`, при падении шлёт алерт в Telegram на `ADMIN_ID` тем же ботом.

Локальная разработка использует `docker-compose.yml` в корне репозитория, не этот каталог.

`push_data.sh` (перенос `game_static.db`/векторов на сервер) — пока руками через `scp`, скрипт появится при следующем обновлении словарей.
