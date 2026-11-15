"""Чистые функции без зависимостей от БД и сети (их легко тестировать)."""
import re
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

PLAYER_ID_RE = re.compile(r"^\d{8,12}$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]{2,}$")


def normalize_player_id(raw: str) -> str | None:
    """Возвращает ID игрока (только цифры, 8-12 знаков) или None."""
    value = (raw or "").strip().replace(" ", "")
    return value if PLAYER_ID_RE.match(value) else None


def valid_email(raw: str | None) -> bool:
    return bool(raw) and len(raw) <= 254 and bool(EMAIL_RE.match(raw))  # type: ignore[arg-type]


def parse_rub(text: str) -> int:
    """'299', '299.5', '299,50' -> копейки. ValueError при мусоре или значении <= 0."""
    try:
        value = Decimal(text.strip().replace(",", ".").replace("₽", ""))
    except InvalidOperation as exc:
        raise ValueError("bad amount") from exc
    kopecks = int((value * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    if kopecks < 0:
        raise ValueError("negative amount")
    return kopecks


def fmt_rub(kopecks: int) -> str:
    rub, kop = divmod(int(kopecks), 100)
    return f"{rub} ₽" if kop == 0 else f"{rub},{kop:02d} ₽"


def kopecks_to_str(kopecks: int) -> str:
    """Формат суммы для API ЮKassa: '299.00'."""
    return f"{int(kopecks) // 100}.{int(kopecks) % 100:02d}"


def str_to_kopecks(value: str) -> int:
    return int((Decimal(value) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
