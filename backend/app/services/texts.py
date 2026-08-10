"""Editable bot texts: DB-backed overrides over hardcoded defaults (admin UI).

Templates use str.format placeholders (e.g. "{word}"). The in-memory cache is
populated at startup from bot_texts (seeded with DEFAULTS on first run) and
kept in sync on every admin write — the bot never queries the DB per message.
"""

import string

from app.db import Database

DEFAULTS: dict[str, str] = {
    "onboarding_1": (
        "Привет! Это «Теплее!» 🌡️\n\nКаждый день я загадываю слово. Пиши свои варианты — "
        "я скажу ранг: насколько твоё слово близко по смыслу.\n\n"
        "🟩 1–100 — очень горячо\n🟨 101–1000 — тепло\n⬜ дальше — холодно"
    ),
    "onboarding_2": (
        "Ранг 1 — победа 🏆\nФорма слова не важна: «котами» = «кот». "
        "Повтор слова попытку не тратит.\n\nПоехали! Напиши первое слово 👇"
    ),
    "help": (
        "🌡️ «Теплее!» — угадай слово дня по смысловой близости.\n\n"
        "Просто пиши слова в чат — ранг покажу в игровом сообщении.\n\n"
        "/lang — сменить язык слова (🇷🇺/🇺🇸)\n"
        "/stats — твоя статистика и стрик\n"
        "/challenge — загадать слово другу\n"
        "/mute — выключить утренние напоминания\n"
        "/help — это сообщение"
    ),
    "word_not_found": "🤷 Не знаю такого слова. Попытка не потрачена!",
    "muted": "🔕 Напоминания выключены. Вернуть: /unmute",
    "unmuted": "🔔 Напоминания включены — жду тебя каждое утро!",
    "hint_no_attempts": "🤷 Сначала напиши хотя бы одно слово — тогда будет от чего подсказывать!",
    "hint_solved": "🏆 Уже угадано, подсказка ни к чему!",
    "challenge_ask_word": (
        "🎯 Напиши слово, которое загадаешь другу — следующим сообщением.\n\n"
        "Нужно существительное из словаря. Передумал? Жми /start — вернёмся к игре."
    ),
    "challenge_pending": "⏳ Готовлю челлендж…",
    "challenge_word_not_found": "🤷 Не знаю такого слова — попробуй другое.",
    "challenge_unavailable": "😔 Челленджи временно недоступны, попробуй позже.",
    "challenge_expired": "😔 Этот челлендж уже не найден — истёк или удалён.",
    "challenge_own_link": "😄 Это же твоя собственная ссылка!",
    "challenge_created": "🎉 Готово! Отправь другу:\n{link}\n\nЯ загадал слово. Слабо угадать? 😏",
    "challenge_intro": "⚔️ {who} загадал тебе слово! Пиши свои варианты 👇",
    "creator_notify": "🏆 {who} угадал твоё слово за {attempts_count} попыток!",
    "game_message_header": (
        "🎯 Слово дня #{day_no} ({flag}) · Попыток: {count} · Подсказок: {hints}"
    ),
    "challenge_message_header": (
        "⚔️ Челлендж от {who} ({flag}) · Попыток: {count} · Подсказок: {hints}"
    ),
    "attempts_last_line": "последнее: {word} — {rank} {emoji}",
    "attempts_top5_label": "Топ-5:",
    "attempts_empty": "Пиши слова — я скажу, насколько ты близко 🌡️",
    "solved_footer": "🏆 Слово угадано! Можно дорешивать — ранги покажу, статистика не пострадает.",
    "full_list_header": "📋 Все слова ({flag}) · Попыток: {count} · Подсказок: {hints}",
    "full_list_empty": "Пока ни одного слова — начни угадывать 🌡️",
    "share_text": (
        "Теплее! #{day_no} {flag} | Попыток: {count} | {boxes} | "
        "Стрик: {streak}🔥 | t.me/{bot_username}"
    ),
    "btn_show_all": "📋 Все слова",
    "btn_hint": "💡 Подсказка",
    "btn_back_to_daily": "🌡️ К слову дня",
    "btn_challenge_new": "🎯 Загадать другу",
    "btn_back_to_challenge": "⚔️ К челленджу",
    "btn_reply_challenge": "🎯 Загадать в ответ",
    "lang_switched": "Режим переключён: теперь угадываем {flag} слово!",
    "stats": (
        "📊 Твоя статистика\n\nПобед: {wins} 🏆\nПопыток всего: {attempts_total}\n"
        "Стрик: {streak}🔥\nЯзык: {flag}"
    ),
    "win_daily": (
        "🎉 Да! Это «{word}» — ранг 1!\n\n"
        "Попыток: {attempts_count} · Подсказок: {hints_used} · Стрик: {streak}🔥\n\n"
        "Поделись результатом:\n{share_text}"
    ),
    "win_challenge": (
        "🎉 Да! Это «{word}» — ранг 1!\n\nПопыток: {attempts_count} · Подсказок: {hints_used}"
    ),
}

LABELS: dict[str, str] = {
    "onboarding_1": "Онбординг: сообщение 1",
    "onboarding_2": "Онбординг: сообщение 2",
    "help": "/help",
    "word_not_found": "Слово не найдено (daily guess)",
    "muted": "/mute подтверждение",
    "unmuted": "/unmute подтверждение",
    "hint_no_attempts": "Подсказка недоступна: нет попыток",
    "hint_solved": "Подсказка недоступна: уже решено",
    "challenge_ask_word": "Запрос слова для челленджа",
    "challenge_pending": "Челлендж создаётся…",
    "challenge_word_not_found": "Слово для челленджа не найдено",
    "challenge_unavailable": "Челленджи недоступны",
    "challenge_expired": "Челлендж истёк/удалён",
    "challenge_own_link": "Переход по своей же ссылке",
    "challenge_created": "Челлендж создан — ссылка другу",
    "challenge_intro": "Вход в чужой челлендж",
    "creator_notify": "Уведомление автору о победе друга",
    "game_message_header": "Заголовок игрового сообщения (daily)",
    "challenge_message_header": "Заголовок игрового сообщения (челлендж)",
    "attempts_last_line": "Строка последней попытки",
    "attempts_top5_label": "Подпись «Топ-5»",
    "attempts_empty": "Пусто: попыток ещё не было",
    "solved_footer": "Плашка «слово угадано»",
    "full_list_header": "Заголовок полного списка попыток",
    "full_list_empty": "Пусто: полный список попыток",
    "share_text": "Текст для шеринга результата",
    "btn_show_all": "Кнопка «Все слова»",
    "btn_hint": "Кнопка «Подсказка»",
    "btn_back_to_daily": "Кнопка «К слову дня»",
    "btn_challenge_new": "Кнопка «Загадать другу»",
    "btn_back_to_challenge": "Кнопка «К челленджу»",
    "btn_reply_challenge": "Кнопка «Загадать в ответ»",
    "lang_switched": "/lang подтверждение",
    "stats": "/stats",
    "win_daily": "Победа: daily",
    "win_challenge": "Победа: челлендж",
}

_cache: dict[str, str] = {}

# Superseded default values, keyed by text key. On startup, any row still holding
# one of these gets bumped to the current DEFAULTS value — it was never edited by
# an admin, just stale from before the default changed. Rows that don't match (i.e.
# admin-edited) are left untouched.
_STALE_DEFAULTS: dict[str, set[str]] = {
    "game_message_header": {"🎯 Слово дня #{day_no} ({flag}) · Попыток: {count}"},
    "challenge_message_header": {"⚔️ Челлендж от {who} ({flag}) · Попыток: {count}"},
    "full_list_header": {"📋 Все слова ({flag}) · Попыток: {count}"},
}


def _placeholders(template: str) -> set[str]:
    return {name for _, name, _, _ in string.Formatter().parse(template) if name}


async def init_cache(db: Database) -> None:
    """Seed bot_texts with any missing defaults, then load everything into memory."""
    global _cache
    await db.conn.executemany(
        "INSERT OR IGNORE INTO bot_texts(key, value) VALUES (?, ?)",
        list(DEFAULTS.items()),
    )
    await db.conn.commit()
    cur = await db.conn.execute("SELECT key, value FROM bot_texts")
    _cache = {row["key"]: row["value"] for row in await cur.fetchall()}

    for key, stale_values in _STALE_DEFAULTS.items():
        if _cache.get(key) in stale_values:
            await set_text(db, key, DEFAULTS[key])


async def set_text(db: Database, key: str, value: str) -> None:
    if key not in DEFAULTS:
        raise KeyError(key)
    allowed = _placeholders(DEFAULTS[key])
    unknown = _placeholders(value) - allowed
    if unknown:
        raise ValueError(f"unknown placeholders: {', '.join(sorted(unknown))}")
    try:
        value.format(**dict.fromkeys(allowed, ""))
    except (IndexError, ValueError) as e:
        raise ValueError("invalid template syntax") from e
    await db.conn.execute(
        "INSERT INTO bot_texts(key, value, updated_at) VALUES (?, ?, datetime('now')) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
        (key, value),
    )
    await db.conn.commit()
    _cache[key] = value


async def reset_text(db: Database, key: str) -> str:
    if key not in DEFAULTS:
        raise KeyError(key)
    await set_text(db, key, DEFAULTS[key])
    return DEFAULTS[key]


def get(key: str, **kwargs: object) -> str:
    """Render a text by key. Falls back to DEFAULTS if the cache isn't loaded yet."""
    template = _cache.get(key, DEFAULTS[key])
    return template.format(**kwargs)


def list_texts() -> list[dict]:
    return [
        {
            "key": key,
            "label": LABELS.get(key, key),
            "value": _cache.get(key, default),
            "default": default,
            "is_overridden": _cache.get(key, default) != default,
            "vars": sorted(_placeholders(default)),
        }
        for key, default in DEFAULTS.items()
    ]
