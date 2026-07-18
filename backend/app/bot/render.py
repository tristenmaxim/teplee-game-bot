"""Game-message rendering: one editable message per user (PRD §5A).

Code/comments in English, user-facing texts in Russian per CLAUDE.md.
"""

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

LANG_FLAG = {"ru": "🇷🇺", "en": "🇬🇧"}


def rank_emoji(rank: int) -> str:
    if rank <= 100:
        return "🟩"
    if rank <= 1000:
        return "🟨"
    return "⬜"


def render_game_message(
    day_no: int,
    lang: str,
    attempts: list[dict],
    last: dict | None,
    solved: bool,
) -> str:
    """attempts are rank-sorted; last is the most recent attempt (word/rank)."""
    lines = [f"🎯 Слово дня #{day_no} ({LANG_FLAG[lang]}) · Попыток: {len(attempts)}"]
    if last:
        lines += ["", f"последнее: {last['word']} — {last['rank']} {rank_emoji(last['rank'])}"]
    if attempts:
        lines += ["", "Топ-5:"]
        lines += [f"{rank_emoji(a['rank'])} {a['rank']} · {a['word']}" for a in attempts[:5]]
    else:
        lines += ["", "Пиши слова — я скажу, насколько ты близко 🌡️"]
    if solved:
        lines += [
            "",
            "🏆 Слово угадано! Можно дорешивать — ранги покажу, статистика не пострадает.",
        ]
    return "\n".join(lines)


def game_keyboard(lang: str) -> InlineKeyboardMarkup:
    """No 'Открыть игру' button: Mini App is deferred to v1.5 (see ROADMAP)."""
    other = "🇬🇧 EN-слово" if lang == "ru" else "🇷🇺 RU-слово"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🎯 Загадать другу", callback_data="challenge"),
                InlineKeyboardButton(text=other, callback_data="toggle_lang"),
            ],
        ]
    )


def share_text(day_no: int, lang: str, attempts: list[dict], streak: int, bot_username: str) -> str:
    greens = sum(1 for a in attempts if a["rank"] <= 100)
    yellows = sum(1 for a in attempts if 100 < a["rank"] <= 1000)
    whites = len(attempts) - greens - yellows
    boxes = "🟩" * min(greens, 3) + "🟨" * min(yellows, 3) + "⬜" * min(whites, 3)
    return (
        f"Теплее! #{day_no} {LANG_FLAG[lang]} | Попыток: {len(attempts)} | "
        f"{boxes} | Стрик: {streak}🔥 | t.me/{bot_username}"
    )


ONBOARDING = [
    "Привет! Это «Теплее!» 🌡️\n\nКаждый день я загадываю слово. Пиши свои варианты — "
    "я скажу ранг: насколько твоё слово близко по смыслу.\n\n"
    "🟩 1–100 — очень горячо\n🟨 101–1000 — тепло\n⬜ дальше — холодно",
    "Ранг 1 — победа 🏆\nФорма слова не важна: «котами» = «кот». "
    "Повтор слова попытку не тратит.\n\nПоехали! Напиши первое слово 👇",
]

HELP_TEXT = (
    "🌡️ «Теплее!» — угадай слово дня по смысловой близости.\n\n"
    "Просто пиши слова в чат — ранг покажу в игровом сообщении.\n\n"
    "/lang — сменить язык слова (🇷🇺/🇬🇧)\n"
    "/stats — твоя статистика и стрик\n"
    "/mute — выключить утренние напоминания\n"
    "/help — это сообщение"
)

WORD_NOT_FOUND = "🤷 Не знаю такого слова. Попытка не потрачена!"
MUTED = "🔕 Напоминания выключены. Вернуть: /unmute"
UNMUTED = "🔔 Напоминания включены — жду тебя каждое утро!"
CHALLENGE_SOON = "🎯 Челленджи уже почти готовы — появятся совсем скоро!"
