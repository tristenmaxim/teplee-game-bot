"""Read-only aggregates + user lookup for the admin dashboard (see app/admin_api.py)."""

import statistics
from datetime import timedelta

from app.db import Database
from app.services import clock

# Extracts the integer day_id out of a daily game_key 'd:<day_id>:<lang>'.
_DAY_ID_FROM_GAME_KEY = "CAST(substr(game_key, 3, instr(substr(game_key, 3), ':') - 1) AS INTEGER)"


async def _retention(db: Database, day_id: int, offset: int) -> dict:
    """Share of the cohort that first played daily on (day_id-offset) who played again on day_id."""
    cohort_day_id = day_id - offset
    cur = await db.conn.execute(
        f"""
        WITH daily_days AS (
            SELECT telegram_id, {_DAY_ID_FROM_GAME_KEY} AS d
            FROM attempts
            WHERE game_key LIKE 'd:%'
            GROUP BY telegram_id, d
        ),
        first_day AS (
            SELECT telegram_id, MIN(d) AS first_day_id
            FROM daily_days
            GROUP BY telegram_id
        )
        SELECT
            COUNT(*) AS cohort,
            SUM(CASE WHEN EXISTS (
                SELECT 1 FROM daily_days dd
                WHERE dd.telegram_id = first_day.telegram_id AND dd.d = ?
            ) THEN 1 ELSE 0 END) AS retained
        FROM first_day
        WHERE first_day_id = ?
        """,
        (day_id, cohort_day_id),
    )
    row = await cur.fetchone()
    cohort = row["cohort"] or 0
    retained = row["retained"] or 0
    return {
        "cohort": cohort,
        "retained": retained,
        "rate": round(retained / cohort, 3) if cohort else None,
    }


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
    win_share_today = round(solved_today / active_today, 3) if active_today else 0.0

    # Median attempts-to-win (dictionary health, PRD §7): tries per (user, game)
    # among games that were won, today's daily games only.
    cur = await db.conn.execute(
        """
        SELECT COUNT(*) AS tries
        FROM attempts a
        WHERE a.game_key LIKE ?
          AND EXISTS (
              SELECT 1 FROM attempts w
              WHERE w.telegram_id = a.telegram_id AND w.game_key = a.game_key AND w.rank = 1
          )
        GROUP BY a.telegram_id, a.game_key
        """,
        (daily_prefix,),
    )
    tries = [r["tries"] for r in await cur.fetchall()]
    median_attempts_to_win = statistics.median(tries) if tries else 0.0

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

    retention_d1 = await _retention(db, day_id, 1)
    retention_d7 = await _retention(db, day_id, 7)
    retention_d30 = await _retention(db, day_id, 30)

    return {
        "day_id": day_id,
        "total_users": total_users,
        "active_today": active_today,
        "solved_today": solved_today,
        "win_share_today": win_share_today,
        "avg_attempts_today": avg_attempts_today,
        "median_attempts_to_win": median_attempts_to_win,
        "muted_users": muted_users,
        "total_challenges": total_challenges,
        "won_challenges": won_challenges,
        "streak_leaders": streak_leaders,
        "retention_d1": retention_d1,
        "retention_d7": retention_d7,
        "retention_d30": retention_d30,
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
