"""Read-only aggregates + user lookup for the admin dashboard (see app/admin_api.py)."""

from datetime import timedelta

from app.db import Database
from app.services import clock


async def dashboard_metrics(db: Database, day_id: int | None = None) -> dict:
    day_id = clock.current_day_id() if day_id is None else day_id
    daily_prefix = f"d:{day_id}:%"

    cur = await db.conn.execute("SELECT COUNT(*) AS n FROM users")
    total_users = (await cur.fetchone())["n"]

    cur = await db.conn.execute(
        "SELECT COUNT(DISTINCT telegram_id) AS players, COUNT(*) AS attempts "
        "FROM attempts WHERE game_key LIKE ?",
        (daily_prefix,),
    )
    row = await cur.fetchone()
    active_today = row["players"] or 0
    avg_attempts_today = round(row["attempts"] / active_today, 1) if active_today else 0.0

    cur = await db.conn.execute(
        "SELECT COUNT(DISTINCT telegram_id) AS n FROM attempts WHERE game_key LIKE ? AND rank = 1",
        (daily_prefix,),
    )
    solved_today = (await cur.fetchone())["n"] or 0

    cur = await db.conn.execute("SELECT COUNT(*) AS n FROM users WHERE notifications = 0")
    muted_users = (await cur.fetchone())["n"]

    cur = await db.conn.execute("SELECT COUNT(*) AS n FROM challenges")
    total_challenges = (await cur.fetchone())["n"]

    cur = await db.conn.execute("SELECT COUNT(*) AS n FROM challenge_results")
    won_challenges = (await cur.fetchone())["n"]

    cur = await db.conn.execute(
        "SELECT telegram_id, username, first_name, streak FROM users "
        "WHERE streak > 0 ORDER BY streak DESC LIMIT 10"
    )
    streak_leaders = [dict(r) for r in await cur.fetchall()]

    return {
        "day_id": day_id,
        "total_users": total_users,
        "active_today": active_today,
        "solved_today": solved_today,
        "avg_attempts_today": avg_attempts_today,
        "muted_users": muted_users,
        "total_challenges": total_challenges,
        "won_challenges": won_challenges,
        "streak_leaders": streak_leaders,
    }


async def search_users(db: Database, query: str, limit: int = 20) -> list[dict]:
    query = query.strip()
    if not query:
        return []
    if query.lstrip("-").isdigit():
        cur = await db.conn.execute("SELECT * FROM users WHERE telegram_id = ?", (int(query),))
    else:
        like = f"%{query}%"
        cur = await db.conn.execute(
            "SELECT * FROM users WHERE username LIKE ? OR first_name LIKE ? "
            "ORDER BY created_at DESC LIMIT ?",
            (like, like, limit),
        )
    rows = [dict(r) for r in await cur.fetchall()]
    for row in rows:
        cur = await db.conn.execute(
            "SELECT COUNT(*) AS n, SUM(CASE WHEN rank = 1 THEN 1 ELSE 0 END) AS wins "
            "FROM attempts WHERE telegram_id = ?",
            (row["telegram_id"],),
        )
        s = await cur.fetchone()
        row["attempts_total"] = s["n"] or 0
        row["wins"] = s["wins"] or 0
    return rows


async def upcoming_words(db: Database, days: int = 7, day_id: int | None = None) -> list[dict]:
    """Next `days` days' answers for ru+en (static.daily_words is read-only, see CLAUDE.md)."""
    day_id = clock.current_day_id() if day_id is None else day_id
    cur = await db.conn.execute(
        "SELECT day_id, lang, word FROM static.daily_words "
        "WHERE day_id >= ? ORDER BY day_id, lang LIMIT ?",
        (day_id, days * 2),
    )
    rows = [dict(r) for r in await cur.fetchall()]
    for row in rows:
        row["date"] = (clock.EPOCH_DATE + timedelta(days=row["day_id"])).isoformat()
    return rows
