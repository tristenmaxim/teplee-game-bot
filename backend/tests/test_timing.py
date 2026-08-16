from app.services import game, timing


def _fake_clock(monkeypatch, times: list[int]):
    it = iter(times)
    monkeypatch.setattr(timing, "_now_ms", lambda: next(it))


async def test_solo_round_target_in_range(db):
    result = await timing.start_round(db, 1, "visible", None)
    assert timing.MIN_TARGET_MS <= result["target_ms"] <= timing.MAX_TARGET_MS
    assert result["mode"] == "visible"


async def test_stop_round_computes_delta(db, monkeypatch):
    _fake_clock(monkeypatch, [1_000_000, 1_003_500])  # started at t, stopped 3500ms later
    start = await timing.start_round(db, 1, "visible", None)
    target = start["target_ms"]

    result = await timing.stop_round(db, 1, start["round_id"])
    assert result["elapsed_ms"] == 3500
    assert result["delta_ms"] == abs(3500 - target)
    assert result["rating"] == timing.rating(result["delta_ms"])


async def test_stop_unknown_round_raises(db):
    try:
        await timing.stop_round(db, 1, "nope")
    except timing.RoundNotFound:
        pass
    else:
        raise AssertionError("expected RoundNotFound")


async def test_stop_twice_raises(db, monkeypatch):
    _fake_clock(monkeypatch, [0, 100, 200])
    start = await timing.start_round(db, 1, "visible", None)
    await timing.stop_round(db, 1, start["round_id"])
    try:
        await timing.stop_round(db, 1, start["round_id"])
    except timing.RoundNotFound:
        pass
    else:
        raise AssertionError("expected RoundNotFound on replay")


async def test_challenge_not_found(db):
    try:
        await timing.start_round(db, 1, "visible", "nope")
    except timing.ChallengeNotFound:
        pass
    else:
        raise AssertionError("expected ChallengeNotFound")


async def test_challenge_flow_one_shot_and_results(db, monkeypatch):
    await game.ensure_user(db, 10, "alice", "Alice")
    await game.ensure_user(db, 20, "bob", "Bob")

    challenge_id = await timing.create_challenge(db, 10, "hidden")
    meta = await timing.challenge_meta(db, challenge_id)
    assert meta["mode"] == "hidden"

    _fake_clock(monkeypatch, [0, 100])  # alice: elapsed 100ms
    r1 = await timing.start_round(db, 10, "visible", challenge_id)
    assert r1["mode"] == "hidden"  # challenge's mode wins over the requested one
    await timing.stop_round(db, 10, r1["round_id"])

    _fake_clock(monkeypatch, [0, 50_000])  # bob: elapsed 50000ms (way off)
    r2 = await timing.start_round(db, 20, "hidden", challenge_id)
    await timing.stop_round(db, 20, r2["round_id"])

    try:
        await timing.start_round(db, 10, "hidden", challenge_id)
    except timing.AlreadyPlayed:
        pass
    else:
        raise AssertionError("expected AlreadyPlayed on replay")

    results = await timing.challenge_results(db, challenge_id)
    assert len(results) == 2
    assert results[0]["label"] == "@alice"  # closer delta sorts first
    assert results[1]["label"] == "@bob"
