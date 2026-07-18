"""Telegram Mini App initData validation (TECH_SPEC §4).

Standard algorithm: secret = HMAC_SHA256(key="WebAppData", msg=bot_token);
hash = hex(HMAC_SHA256(key=secret, msg=data_check_string)). telegram_id from
the request body is never trusted — identity comes only from validated initData.
"""

import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from urllib.parse import parse_qsl


class InvalidInitData(Exception):
    pass


@dataclass
class TelegramUser:
    id: int
    username: str | None
    first_name: str | None


def validate_init_data(
    init_data_raw: str, bot_token: str, max_age_s: int = 24 * 3600
) -> TelegramUser:
    try:
        pairs = dict(parse_qsl(init_data_raw, strict_parsing=True))
    except ValueError as e:
        raise InvalidInitData("malformed query string") from e

    received_hash = pairs.pop("hash", None)
    if not received_hash:
        raise InvalidInitData("missing hash")

    check_string = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))
    secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    expected = hmac.new(secret, check_string.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, received_hash):
        raise InvalidInitData("bad signature")

    auth_date = int(pairs.get("auth_date", "0"))
    if time.time() - auth_date > max_age_s:
        raise InvalidInitData("initData expired")

    try:
        user = json.loads(pairs["user"])
        return TelegramUser(
            id=int(user["id"]),
            username=user.get("username"),
            first_name=user.get("first_name"),
        )
    except (KeyError, ValueError, json.JSONDecodeError) as e:
        raise InvalidInitData("missing user") from e


def sign_init_data(pairs: dict[str, str], bot_token: str) -> str:
    """Build a signed initData string — test fixtures and local tooling only."""
    from urllib.parse import urlencode

    check_string = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))
    secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    digest = hmac.new(secret, check_string.encode(), hashlib.sha256).hexdigest()
    return urlencode({**pairs, "hash": digest})
