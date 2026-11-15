import logging
import re

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field

from . import catalog, orders
from .config import get_settings
from .models import Order, Status
from .security import InitDataError, validate_init_data
from .utils import fmt_rub

log = logging.getLogger("api")
settings = get_settings()
router = APIRouter()

PAYMENT_ID_RE = re.compile(r"^[A-Za-z0-9\-]{10,64}$")


async def current_user(authorization: str = Header(default="")) -> dict:
    scheme, _, data = authorization.partition(" ")
    if scheme.lower() != "tma" or not data:
        raise HTTPException(401, "Откройте магазин через Telegram")
    try:
        return validate_init_data(data, settings.bot_token)
    except InitDataError:
        raise HTTPException(401, "Сессия недействительна, перезапустите мини-приложение") from None


class OrderIn(BaseModel):
    product_id: int
    player_id: str = Field(max_length=32)
    email: str | None = Field(default=None, max_length=254)


def order_out(o: Order) -> dict:
    return {
        "id": o.id,
        "short": o.short,
        "uc": o.uc,
        "price_text": fmt_rub(o.price),
        "player_id": o.player_id,
        "status": o.status,
        "status_text": orders.STATUS_TEXT.get(o.status, o.status),
        "created_at": o.created_at.isoformat() if o.created_at else None,
        "payment_url": o.payment_url if o.status == Status.PENDING else None,
    }


@router.get("/api/config")
async def get_config() -> dict:
    return {
        "receipt_required": settings.receipt_enabled,
        "support": settings.support_username,
        "eta": settings.delivery_eta_text,
    }


@router.get("/api/products")
async def get_products(_: dict = Depends(current_user)) -> list[dict]:
    return [
        {"id": p.id, "uc": p.uc, "title": p.title, "price": p.price, "price_text": fmt_rub(p.price)}
        for p in await catalog.list_active()
    ]


@router.post("/api/orders")
async def post_order(body: OrderIn, user: dict = Depends(current_user)) -> dict:
    try:
        order = await orders.create_order(user, body.product_id, body.player_id, body.email)
    except orders.ShopError as exc:
        raise HTTPException(400, exc.message) from None
    return order_out(order)


@router.get("/api/orders")
async def get_orders(user: dict = Depends(current_user)) -> list[dict]:
    return [order_out(o) for o in await orders.user_orders(int(user["id"]), limit=30)]


@router.get("/api/orders/{order_id}")
async def get_order(order_id: str, user: dict = Depends(current_user)) -> dict:
    order = await orders.get_user_order(int(user["id"]), order_id)
    if order is None:
        raise HTTPException(404, "Заказ не найден")
    return order_out(order)


@router.post("/webhooks/yookassa")
async def yookassa_webhook(request: Request) -> dict:
    """HTTP-уведомление ЮKassa. Содержимому не доверяем: статус перепроверяется через API.
    Если проверка упала (например, сеть), отдаём 500 — ЮKassa повторит доставку."""
    try:
        body = await request.json()
        event = str(body["event"])
        payment_id = str(body["object"]["id"])
    except Exception:
        raise HTTPException(400, "bad payload") from None
    if not event.startswith("payment.") or not PAYMENT_ID_RE.match(payment_id):
        return {"ok": True}
    await orders.confirm_payment(payment_id)
    return {"ok": True}
