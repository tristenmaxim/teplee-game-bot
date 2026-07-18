from app.bot.render import rank_emoji, render_game_message, share_text


def test_rank_emoji_zones():
    assert rank_emoji(1) == "🟩"
    assert rank_emoji(100) == "🟩"
    assert rank_emoji(101) == "🟨"
    assert rank_emoji(1000) == "🟨"
    assert rank_emoji(1001) == "⬜"


def test_render_empty_state():
    text = render_game_message(42, "ru", [], None, solved=False)
    assert "Слово дня #42" in text and "🇷🇺" in text and "Попыток: 0" in text
    assert "Пиши слова" in text


def test_render_top5_and_last():
    attempts = [{"word": f"w{i}", "rank": r} for i, r in enumerate([14, 88, 250, 610, 3400, 9000])]
    text = render_game_message(42, "en", attempts, {"word": "животное", "rank": 250}, False)
    assert "последнее: животное — 250 🟨" in text
    top5_section = text.split("Топ-5:")[1]
    assert top5_section.count("·") == 5  # top-5 only, sixth attempt not shown
    assert "🟩 14 · w0" in text and "⬜ 3400 · w4" in text
    assert "w5" not in text


def test_render_solved_banner():
    text = render_game_message(1, "ru", [{"word": "кот", "rank": 1}], None, solved=True)
    assert "🏆" in text


def test_share_text_no_spoilers():
    attempts = [{"word": "секретище", "rank": 1}, {"word": "тепло", "rank": 500}]
    s = share_text(42, "ru", attempts, streak=5, bot_username="teplee_game_bot")
    assert "секретище" not in s and "тепло" not in s
    assert "#42" in s and "Стрик: 5🔥" in s and "t.me/teplee_game_bot" in s
