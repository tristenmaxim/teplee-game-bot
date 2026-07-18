"""Game day arithmetic: day_id = (msk_date - EPOCH_DATE).days (CLAUDE.md)."""

from datetime import date, datetime
from zoneinfo import ZoneInfo

MSK = ZoneInfo("Europe/Moscow")
EPOCH_DATE = date(2026, 8, 1)


def msk_today(now: datetime | None = None) -> date:
    now = now or datetime.now(tz=MSK)
    return now.astimezone(MSK).date()


def current_day_id(now: datetime | None = None) -> int:
    return (msk_today(now) - EPOCH_DATE).days
