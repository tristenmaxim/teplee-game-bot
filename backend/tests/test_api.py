import time

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app import api
from app.auth import sign_init_data
from app.main import app
from tests.conftest import BOT_TOKEN


def auth_headers(user_id: int = 777) -> dict[str, str]:
    raw = sign_init_data(
        {
            "auth_date": str(int(time.time())),
            "user": f'{{"id":{user_id},"first_name":"Test","username":"tester"}}',
        },
        BOT_TOKEN,
    )
    return {"Authorization": f"tma {raw}"}


@pytest_asyncio.fixture
async def client(db, monkeypatch):
    app.state.db = db
    # daily key must point at the fixture's day 0 regardless of wall clock
    monkeypatch.setattr(api.game, "daily_game_key", lambda lang, day_id=None: f"d:0:{lang}")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as c:
        yield c


async def test_requires_auth(client):
    assert (await client.get("/api/state")).status_code == 401
    bad = await client.get("/api/state", headers={"Authorization": "tma junk"})
    assert bad.status_code == 401


async def test_guess_flow(client):
    h = auth_headers()
    r = await client.post("/api/guess", json={"word": "кошками"}, headers=h)
    assert r.status_code == 200
    body = r.json()
    assert body["word"] == "кошка" and body["rank"] == 2 and body["is_new"]

    # repeat -> same rank, not new
    r2 = await client.post("/api/guess", json={"word": "кошка"}, headers=h)
    assert r2.json()["is_new"] is False and r2.json()["attempts_count"] == 1

    # state reflects the attempt
    s = (await client.get("/api/state", headers=h)).json()
    assert s["attempts_count"] == 1 and s["solved"] is False

    # win
    w = (await client.post("/api/guess", json={"word": "кот"}, headers=h)).json()
    assert w["is_win"] and w["streak"] == 1


async def test_word_not_found_409(client):
    r = await client.post("/api/guess", json={"word": "жмыхокрут"}, headers=auth_headers())
    assert r.status_code == 409
    assert r.json()["detail"] == "word_not_found"


async def test_lang_switch(client):
    h = auth_headers()
    assert (await client.post("/api/lang", json={"lang": "en"}, headers=h)).status_code == 200
    r = await client.post("/api/guess", json={"word": "dog"}, headers=h)
    assert r.json()["rank"] == 2  # looked up in the EN puzzle now
    assert (await client.post("/api/lang", json={"lang": "xx"}, headers=h)).status_code == 422


async def test_stats_endpoint(client):
    h = auth_headers(user_id=555)
    await client.post("/api/guess", json={"word": "кот"}, headers=h)
    s = (await client.get("/api/stats", headers=h)).json()
    assert s["wins"] == 1 and s["streak"] == 1


async def test_rate_limit(client, monkeypatch):
    monkeypatch.setattr(api, "guess_bucket", api.TokenBucket(rate=1.0, capacity=2))
    h = auth_headers(user_id=999)
    codes = []
    for _ in range(4):
        r = await client.post("/api/guess", json={"word": "собака"}, headers=h)
        codes.append(r.status_code)
    assert 429 in codes and codes[0] == 200


async def test_forged_telegram_id_ignored(client):
    """Body/query cannot spoof identity — it comes only from initData."""
    h = auth_headers(user_id=111)
    await client.post("/api/guess", json={"word": "кот", "telegram_id": 42}, headers=h)
    s = (await client.get("/api/stats", headers=h)).json()
    assert s["wins"] == 1  # attempt landed on user 111, not 42
