import time
from datetime import UTC, date, datetime

import pytest

from app.auth import InvalidInitData, sign_init_data, validate_init_data
from app.services import clock, game
from app.services.lemmatize import lemma_ru, lookup_candidates, normalize
from tests.conftest import BOT_TOKEN

# --- clock ---

def test_day_id_epoch():
    assert clock.current_day_id(datetime(2026, 8, 1, 12, 0, tzinfo=clock.MSK)) == 0
    assert clock.current_day_id(datetime(2026, 8, 2, 0, 0, tzinfo=clock.MSK)) == 1


def test_day_id_msk_boundary():
    # 2026-08-01 23:30 UTC is already 2026-08-02 02:30 in Moscow
    utc = datetime(2026, 8, 1, 23, 30, tzinfo=UTC)
    assert clock.current_day_id(utc) == 1
    assert clock.msk_today(utc) == date(2026, 8, 2)


# --- lemmatization ---

def test_normalize_lower_and_yo():
    assert normalize("  Ёжик ") == "ежик"


def test_lemma_ru_wordforms():
    assert lemma_ru("котами") == "кот"
    assert lemma_ru("собаки") == "собака"


def test_lemma_ru_dengi_override():
    assert lemma_ru("деньги") == "деньги"
    assert lemma_ru("денег") == "деньги"


def test_lookup_candidates_surface_first():
    # "пар" lemmatizes to "пара" — surface form must come first
    assert lookup_candidates("пар", "ru")[0] == "пар"


def test_lookup_candidates_en(en_forms):
    assert lookup_candidates("Apples", "en") == ["apples", "apple"]
    assert lookup_candidates("cat", "en") == ["cat"]


# --- guess engine ---

async def test_guess_new_word(db):
    r = await game.guess(db, 1, "d:0:ru", "ru", "кошка")
    assert (r.word, r.rank, r.is_new, r.is_win) == ("кошка", 2, True, False)
    assert r.attempts_count == 1


async def test_guess_wordform_resolves(db):
    r = await game.guess(db, 1, "d:0:ru", "ru", "КОШКАМИ")
    assert r.word == "кошка" and r.rank == 2


async def test_guess_repeat_not_counted(db):
    await game.guess(db, 1, "d:0:ru", "ru", "кошка")
    r = await game.guess(db, 1, "d:0:ru", "ru", "кошка")
    assert r.is_new is False and r.attempts_count == 1


async def test_guess_not_found(db):
    with pytest.raises(game.WordNotFound):
        await game.guess(db, 1, "d:0:ru", "ru", "абракадабрище")


async def test_guess_win_and_streak(db):
    r = await game.guess(db, 1, "d:0:ru", "ru", "кот")
    assert r.is_win and r.streak == 1
    # next day win extends the streak
    r2 = await game.guess(db, 1, "d:1:ru", "ru", "собака")
    assert r2.is_win and r2.streak == 2
    # replaying the winning word does not bump anything
    r3 = await game.guess(db, 1, "d:1:ru", "ru", "собака")
    assert r3.streak == 2 and r3.is_new is False


async def test_streak_resets_after_gap(db):
    await game.guess(db, 1, "d:0:ru", "ru", "кот")
    # day 1 skipped -> the day-3 win starts a fresh streak
    r = await game.guess(db, 1, "d:3:ru", "ru", "кот")
    assert r.is_win and r.streak == 1


async def test_state_sync(db):
    await game.guess(db, 1, "d:0:ru", "ru", "собака")
    await game.guess(db, 1, "d:0:ru", "ru", "кот")
    s = await game.state(db, 1, "d:0:ru", "ru")
    assert s["solved"] and s["attempts_count"] == 2
    assert [a["word"] for a in s["attempts"]] == ["кот", "собака"]  # sorted by rank
    assert s["day_no"] == 0


async def test_homograph_par_playable(db):
    r = await game.guess(db, 1, "d:0:ru", "ru", "пар")
    assert r.word == "пар" and r.rank == 200


async def test_stats(db):
    await game.guess(db, 1, "d:0:ru", "ru", "кот")
    s = await game.stats(db, 1)
    assert s["wins"] == 1 and s["attempts_total"] == 1 and s["streak"] == 1


# --- initData ---

def _make_init_data(user_id=777, auth_date=None, token=BOT_TOKEN):
    pairs = {
        "auth_date": str(auth_date or int(time.time())),
        "query_id": "AAF03QwzAAAAAPTdDDMYq",
        "user": f'{{"id":{user_id},"first_name":"Test","username":"tester"}}',
    }
    return sign_init_data(pairs, token)


def test_init_data_valid():
    user = validate_init_data(_make_init_data(), BOT_TOKEN)
    assert user.id == 777 and user.username == "tester"


def test_init_data_forged_signature():
    forged = _make_init_data(token="6666:OTHER_TOKEN")
    with pytest.raises(InvalidInitData):
        validate_init_data(forged, BOT_TOKEN)


def test_init_data_tampered_user():
    raw = _make_init_data(user_id=777)
    tampered = raw.replace("777", "999")
    with pytest.raises(InvalidInitData):
        validate_init_data(tampered, BOT_TOKEN)


def test_init_data_expired():
    old = _make_init_data(auth_date=int(time.time()) - 100_000)
    with pytest.raises(InvalidInitData):
        validate_init_data(old, BOT_TOKEN)
