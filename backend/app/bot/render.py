"""Game-message rendering: one editable message per user (PRD §5A).

Code/comments in English, user-facing texts in Russian per CLAUDE.md.
"""

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.services import challenge

LANG_FLAG = {"ru": "🇷🇺", "en": "🇬🇧"}


def rank_emoji(rank: int) -> str:
    if rank <= 100:
        return "🟩"
    if rank <= 1000:
        return "🟨"
    return "⬜"


def _attempts_body(attempts: list[dict], last: dict | None, solved: bool) -> list[str]:
    """Shared "последнее/Топ-5/solved-footer" body for daily and challenge messages."""
    lines = []
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
    return lines


def render_game_message(
    day_no: int,
    lang: str,
    attempts: list[dict],
    last: dict | None,
    solved: bool,
) -> str:
    """attempts are rank-sorted; last is the most recent attempt (word/rank)."""
    lines = [f"🎯 Слово дня #{day_no} ({LANG_FLAG[lang]}) · Попыток: {len(attempts)}"]
    lines += _attempts_body(attempts, last, solved)
    return "\n".join(lines)


def render_challenge_message(
    who: str,
    lang: str,
    attempts: list[dict],
    last: dict | None,
    solved: bool,
) -> str:
    """Same body as render_game_message, but headed by the challenge creator, no day number."""
    lines = [f"⚔️ Челлендж от {who} ({LANG_FLAG[lang]}) · Попыток: {len(attempts)}"]
    lines += _attempts_body(attempts, last, solved)
    return "\n".join(lines)


def game_keyboard(in_challenge: bool = False) -> InlineKeyboardMarkup:
    """No 'Открыть игру' button: Mini App is deferred to v1.5 (see ROADMAP).

    in_challenge=True: playing someone else's challenge, so swap the "загадать
    другу" row for a way back to the daily word. in_challenge=False (default,
    daily play): "Загадать другу" opens a stateless how-to alert rather than a
    dialog — Telegram gives bots no way to prefill a user's next message, so
    the button can't do more than tell them to type /challenge <слово>.
    """
    if in_challenge:
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="📋 Все слова", callback_data="show_all")],
                [InlineKeyboardButton(text="💡 Подсказка", callback_data="hint")],
                [InlineKeyboardButton(text="🌡️ К слову дня", callback_data="back_to_daily")],
            ]
        )
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📋 Все слова", callback_data="show_all")],
            [InlineKeyboardButton(text="💡 Подсказка", callback_data="hint")],
            [InlineKeyboardButton(text="🎯 Загадать другу", callback_data="challenge_howto")],
        ]
    )


def challenge_win_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🎯 Загадать в ответ", callback_data="reply_challenge")]
        ]
    )


def render_full_list(attempts: list[dict], lang: str) -> str:
    """Full rank-sorted attempts list, unlike render_game_message's top-5 preview."""
    lines = [f"📋 Все слова ({LANG_FLAG[lang]}) · Попыток: {len(attempts)}"]
    if attempts:
        lines += ["", *[f"{rank_emoji(a['rank'])} {a['rank']} · {a['word']}" for a in attempts]]
    else:
        lines += ["", "Пока ни одного слова — начни угадывать 🌡️"]
    return "\n".join(lines)


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
    "/challenge <слово> — загадать слово другу\n"
    "/mute — выключить утренние напоминания\n"
    "/help — это сообщение"
)

WORD_NOT_FOUND = "🤷 Не знаю такого слова. Попытка не потрачена!"
MUTED = "🔕 Напоминания выключены. Вернуть: /unmute"
UNMUTED = "🔔 Напоминания включены — жду тебя каждое утро!"
HINT_NO_ATTEMPTS = "🤷 Сначала напиши хотя бы одно слово — тогда будет от чего подсказывать!"
HINT_SOLVED = "🏆 Уже угадано, подсказка ни к чему!"

CHALLENGE_USAGE = (
    "🎯 Загадай слово другу: напиши `/challenge <слово>`, например `/challenge космос`. "
    "Слово должно быть существительным из словаря."
)
CHALLENGE_HOWTO = CHALLENGE_USAGE
CHALLENGE_PENDING = "⏳ Готовлю челлендж…"
CHALLENGE_WORD_NOT_FOUND = "🤷 Не знаю такого слова — попробуй другое."
CHALLENGE_LIMIT = (
    f"У тебя уже {challenge.MAX_ACTIVE} активных челленджей — подожди, пока кто-то из них "
    f"истечёт (живут {challenge.TTL_DAYS} дней)."
)
CHALLENGE_UNAVAILABLE = "😔 Челленджи временно недоступны, попробуй позже."
CHALLENGE_EXPIRED = "😔 Этот челлендж уже не найден — истёк или удалён."
CHALLENGE_OWN_LINK = "😄 Это же твоя собственная ссылка!"


def challenge_created_text(link: str) -> str:
    return f"🎉 Готово! Отправь другу:\n{link}\n\nЯ загадал слово. Слабо угадать? 😏"


def challenge_intro_text(who: str) -> str:
    return f"⚔️ {who} загадал тебе слово! Пиши свои варианты 👇"


def creator_notify_text(who: str, attempts_count: int) -> str:
    return f"🏆 {who} угадал твоё слово за {attempts_count} попыток!"
