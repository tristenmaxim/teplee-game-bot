#!/bin/sh
# /api/health is not exposed publicly (no domain/Caddy in this phase — see
# DEPLOY.md Фаза 1), so we check it locally on the VPS and alert via the bot's
# own Telegram API if it's down. Installed via cron:
# */5 * * * * /opt/teplee/healthcheck.sh >> /opt/teplee/healthcheck.log 2>&1
set -eu

cd /opt/teplee
# shellcheck disable=SC1091
. ./.env

if ! curl -sf -m 5 http://localhost:8000/api/health > /dev/null; then
  echo "$(date -Is) health check FAILED"
  if [ -n "${ADMIN_ID:-}" ]; then
    curl -s -m 5 "https://api.telegram.org/bot${BOT_TOKEN}/sendMessage" \
      -d chat_id="$ADMIN_ID" \
      -d text="⚠️ Теплее! backend не отвечает на /api/health" > /dev/null
  fi
fi
