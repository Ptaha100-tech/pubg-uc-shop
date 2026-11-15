"""Проверка подписи initData из Telegram Mini App.

Документация: https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app
"""
import hashlib
import hmac
import json
import time
from urllib.parse import parse_qsl


class InitDataError(Exception):
    pass


def validate_init_data(
    init_data: str,
    bot_token: str,
    max_age: int = 24 * 3600,
    now: float | None = None,
) -> dict:
    """Проверяет подпись и свежесть initData, возвращает dict пользователя Telegram."""
    if not init_data or len(init_data) > 8192:
        raise InitDataError("empty or too long")

    pairs = dict(parse_qsl(init_data, keep_blank_values=True))
    received_hash = pairs.pop("hash", None)
    if not received_hash:
        raise InitDataError("no hash")

    check_string = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))
    secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    expected = hmac.new(secret, check_string.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, received_hash):
        raise InitDataError("bad signature")

    try:
        auth_date = int(pairs.get("auth_date", "0"))
    except ValueError as exc:
        raise InitDataError("bad auth_date") from exc
    if (now if now is not None else time.time()) - auth_date > max_age:
        raise InitDataError("expired")

    try:
        user = json.loads(pairs["user"])
        int(user["id"])
    except (KeyError, ValueError, TypeError) as exc:
        raise InitDataError("no user") from exc
    return user
