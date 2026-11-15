"""Тесты чистой логики (подпись initData, суммы, валидация). Не требуют сети и БД."""
import hashlib
import hmac
import json
import sys
import time
from pathlib import Path
from urllib.parse import urlencode

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.security import InitDataError, validate_init_data  # noqa: E402
from app.utils import (  # noqa: E402
    fmt_rub,
    kopecks_to_str,
    normalize_player_id,
    parse_rub,
    str_to_kopecks,
    valid_email,
)

TOKEN = "123456:TEST-TOKEN"


def make_init_data(token: str = TOKEN, auth_date: int | None = None, **extra) -> str:
    fields = {
        "auth_date": str(auth_date if auth_date is not None else int(time.time())),
        "query_id": "AAH123",
        "user": json.dumps({"id": 42, "first_name": "Иван", "username": "ivan"}, ensure_ascii=False),
        **extra,
    }
    check = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    fields["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urlencode(fields)


def test_valid_init_data():
    user = validate_init_data(make_init_data(), TOKEN)
    assert user["id"] == 42 and user["username"] == "ivan"


def test_signature_field_is_part_of_check_string():
    assert validate_init_data(make_init_data(signature="abc"), TOKEN)["id"] == 42


def test_wrong_token_rejected():
    with pytest.raises(InitDataError):
        validate_init_data(make_init_data(), "999:OTHER")


def test_tampered_payload_rejected():
    data = make_init_data().replace("%22id%22%3A+42", "%22id%22%3A+1")
    with pytest.raises(InitDataError):
        validate_init_data(data, TOKEN)


def test_expired_rejected():
    old = make_init_data(auth_date=int(time.time()) - 3 * 24 * 3600)
    with pytest.raises(InitDataError):
        validate_init_data(old, TOKEN)


@pytest.mark.parametrize("bad", ["", "hash=abc", "user=%7B%7D", "a" * 9000])
def test_garbage_rejected(bad):
    with pytest.raises(InitDataError):
        validate_init_data(bad, TOKEN)


@pytest.mark.parametrize(
    "raw,expected",
    [("5123456789", "5123456789"), (" 5123 4567 89 ", "5123456789"), ("1234567", None),
     ("1234567890123", None), ("abc12345678", None), ("", None)],
)
def test_player_id(raw, expected):
    assert normalize_player_id(raw) == expected


def test_money():
    assert parse_rub("299") == 29900
    assert parse_rub("299,5") == 29950
    assert parse_rub("1 ₽".replace(" ", "")) == 100
    assert fmt_rub(29900) == "299 ₽" and fmt_rub(29950) == "299,50 ₽"
    assert kopecks_to_str(29905) == "299.05" and kopecks_to_str(100) == "1.00"
    assert str_to_kopecks("299.00") == 29900
    with pytest.raises(ValueError):
        parse_rub("abc")
    with pytest.raises(ValueError):
        parse_rub("-5")


def test_email():
    assert valid_email("a@b.co") and not valid_email("a@b") and not valid_email(None) and not valid_email("")
