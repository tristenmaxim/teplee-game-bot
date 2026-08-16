"""Game-message rendering: one editable message per user (PRD §5A).

Code/comments in English, user-facing texts in Russian per CLAUDE.md.
User-facing strings live in app.services.texts (DB-editable via admin UI),
not as literals here — this module only assembles them.
"""

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo

from app.config import get_settings
from app.services import texts

LANG_FLAG = {"ru": "🇷🇺", "en": "🇺🇸"}


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
        lines += [
            "",
            texts.get(
                "attempts_last_line", word=last["word"], rank=last["rank"],
                emoji=rank_emoji(last["rank"]),
            ),
        ]
    if attempts:
        lines += ["", texts.get("attempts_top5_label")]
        lines += [f"{rank_emoji(a['rank'])} {a['rank']} · {a['word']}" for a in attempts[:5]]
    else:
        lines += ["", texts.get("attempts_empty")]
    if solved:
        lines += ["", texts.get("solved_footer")]
    return lines


def render_game_message(
    day_no: int,
    lang: str,
    attempts: list[dict],
    last: dict | None,
    solved: bool,
    hints_used: int,
) -> str:
    """attempts are rank-sorted; last is the most recent attempt (word/rank)."""
    lines = [
        texts.get(
            "game_message_header",
            day_no=day_no,
            flag=LANG_FLAG[lang],
            count=len(attempts),
            hints=hints_used,
        )
    ]
    lines += _attempts_body(attempts, last, solved)
    return "\n".join(lines)


def render_challenge_message(
    who: str,
    lang: str,
    attempts: list[dict],
    last: dict | None,
    solved: bool,
    hints_used: int,
) -> str:
    """Same body as render_game_message, but headed by the challenge creator, no day number."""
    lines = [
        texts.get(
            "challenge_message_header",
            who=who,
            flag=LANG_FLAG[lang],
            count=len(attempts),
            hints=hints_used,
        )
    ]
    lines += _attempts_body(attempts, last, solved)
    return "\n".join(lines)


def game_keyboard(
    in_challenge: bool = False, has_challenge_to_return_to: bool = False
) -> InlineKeyboardMarkup:
    """No 'Открыть игру' button: Mini App is deferred to v1.5 (see ROADMAP).

    in_challenge=True: playing someone else's challenge, so swap the "загадать
    другу" row for a way back to the daily word. in_challenge=False (default,
    daily play): "Загадать другу" arms users.awaiting_challenge, so the next
    plain message is read as the secret word instead of a guess — Telegram
    gives bots no way to prefill a message, and typing "/challenge слово" by
    hand proved awkward.

    has_challenge_to_return_to (ignored when in_challenge=True): the user has
    a last-played friend's challenge still valid, so add a way back into it —
    otherwise "back to daily" is a one-way trip out of a challenge.
    """
    open_app_row = [
        InlineKeyboardButton(
            text=texts.get("btn_open_app"), web_app=WebAppInfo(url=get_settings().webapp_url)
        )
    ]
    if in_challenge:
        return InlineKeyboardMarkup(
            inline_keyboard=[
                open_app_row,
                [InlineKeyboardButton(text=texts.get("btn_show_all"), callback_data="show_all")],
                [InlineKeyboardButton(text=texts.get("btn_hint"), callback_data="hint")],
                [
                    InlineKeyboardButton(
                        text=texts.get("btn_back_to_daily"), callback_data="back_to_daily"
                    )
                ],
            ]
        )
    rows = [
        open_app_row,
        [InlineKeyboardButton(text=texts.get("btn_show_all"), callback_data="show_all")],
        [InlineKeyboardButton(text=texts.get("btn_hint"), callback_data="hint")],
        [InlineKeyboardButton(text=texts.get("btn_challenge_new"), callback_data="challenge_new")],
    ]
    if has_challenge_to_return_to:
        rows.append(
            [
                InlineKeyboardButton(
                    text=texts.get("btn_back_to_challenge"), callback_data="back_to_challenge"
                )
            ]
        )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def challenge_win_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=texts.get("btn_reply_challenge"), callback_data="reply_challenge"
                )
            ]
        ]
    )


def render_full_list(attempts: list[dict], lang: str, hints_used: int) -> str:
    """Full rank-sorted attempts list, unlike render_game_message's top-5 preview."""
    lines = [
        texts.get(
            "full_list_header", flag=LANG_FLAG[lang], count=len(attempts), hints=hints_used
        )
    ]
    if attempts:
        lines += ["", *[f"{rank_emoji(a['rank'])} {a['rank']} · {a['word']}" for a in attempts]]
    else:
        lines += ["", texts.get("full_list_empty")]
    return "\n".join(lines)


def share_text(day_no: int, lang: str, attempts: list[dict], streak: int, bot_username: str) -> str:
    greens = sum(1 for a in attempts if a["rank"] <= 100)
    yellows = sum(1 for a in attempts if 100 < a["rank"] <= 1000)
    whites = len(attempts) - greens - yellows
    boxes = "🟩" * min(greens, 3) + "🟨" * min(yellows, 3) + "⬜" * min(whites, 3)
    return texts.get(
        "share_text",
        day_no=day_no,
        flag=LANG_FLAG[lang],
        count=len(attempts),
        boxes=boxes,
        streak=streak,
        bot_username=bot_username,
    )


def challenge_created_text(link: str) -> str:
    return texts.get("challenge_created", link=link)


def challenge_intro_text(who: str) -> str:
    return texts.get("challenge_intro", who=who)


def creator_notify_text(who: str, attempts_count: int) -> str:
    return texts.get("creator_notify", who=who, attempts_count=attempts_count)
