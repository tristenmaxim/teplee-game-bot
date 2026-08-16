from app.services import wordle


def test_feedback_all_hit():
    assert wordle.feedback("кошка", "кошка") == ["hit"] * 5


def test_feedback_present_and_miss():
    # answer "кошка" has two 'к's (pos 0, 3); guess "какао" hits the first 'к',
    # finds the second 'к' and the single 'о'/'а' elsewhere (present), and runs
    # out of 'а's for the second occurrence (miss).
    assert wordle.feedback("какао", "кошка") == ["hit", "present", "present", "miss", "present"]


def test_feedback_duplicate_letters_not_overcounted():
    # answer "манго" has one 'а'; guess "залах"-like case: two 'а's in guess, one in answer
    assert wordle.feedback("апапа", "манго") == ["present", "miss", "miss", "miss", "miss"]


def test_daily_word_is_five_letters_and_stable():
    w = wordle.daily_word(0)
    assert len(w) == 5
    assert wordle.daily_word(0) == w  # deterministic


async def test_guess_flow_invalid_then_valid(db):
    game_key = wordle.daily_game_key(0)
    try:
        await wordle.guess(db, 1, game_key, "ыыыыы")
    except wordle.InvalidGuess:
        pass
    else:
        raise AssertionError("expected InvalidGuess")

    other = wordle.daily_word(1)  # different shuffle slot, guaranteed != day 0's answer
    result = await wordle.guess(db, 1, game_key, other)
    assert result.attempts[-1].word == other
    assert not result.solved and not result.game_over


async def test_guess_win_updates_streak(db):
    game_key = wordle.daily_game_key(0)
    answer = wordle.daily_word(0)
    result = await wordle.guess(db, 2, game_key, answer)
    assert result.solved and result.game_over
    assert result.streak == 1

    state = await wordle.state(db, 2, game_key)
    assert state["solved"] and state["answer"] == answer


async def test_guess_after_win_raises_game_over(db):
    game_key = wordle.daily_game_key(0)
    answer = wordle.daily_word(0)
    await wordle.guess(db, 3, game_key, answer)
    try:
        await wordle.guess(db, 3, game_key, answer)
    except wordle.GameOver:
        pass
    else:
        raise AssertionError("expected GameOver")


async def test_six_wrong_attempts_ends_game_without_reveal_before(db):
    game_key = wordle.daily_game_key(0)
    answer = wordle.daily_word(0)
    wrong_words = [w for w in wordle._ANSWERS if w != answer][: wordle.MAX_ATTEMPTS]

    for i, w in enumerate(wrong_words):
        result = await wordle.guess(db, 4, game_key, w)
        state = await wordle.state(db, 4, game_key)
        if i < wordle.MAX_ATTEMPTS - 1:
            assert state["answer"] is None
            assert not result.game_over
        else:
            assert result.game_over and not result.solved
            assert state["answer"] == answer
