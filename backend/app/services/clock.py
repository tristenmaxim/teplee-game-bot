"""Game day arithmetic: day_id = (msk_date - EPOCH_DATE).days (CLAUDE.md)."""

import os
from datetime import date, datetime
from zoneinfo import ZoneInfo

MSK = ZoneInfo("Europe/Moscow")
# Launch date; override (GAME_EPOCH_DATE=YYYY-MM-DD) for local runs before launch.
EPOCH_DATE = date.fromisoformat(os.environ.get("GAME_EPOCH_DATE", "2026-08-01"))


def msk_today(now: datetime | None = None) -> date:
    now = now or datetime.now(tz=MSK)
    return now.astimezone(MSK).date()


def current_day_id(now: datetime | None = None) -> int:
    return (msk_today(now) - EPOCH_DATE).days
