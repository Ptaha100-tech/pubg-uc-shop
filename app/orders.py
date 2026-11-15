"""Бизнес-логика заказов: создание, подтверждение оплаты, выдача, возврат, сверка.

Все переходы статусов сделаны атомарными UPDATE ... WHERE status = ..., поэтому
повторный вебхук, двойной клик админа или одновременная сверка не дадут двойной выдачи.
"""
import asyncio
import logging
from datetime import datetime, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError

from . import notify
from .config import get_settings
from .db import SessionLocal
from .models import Order, Product, Status, User, utcnow
from .suppliers import DeliveryResult, get_supplier
from .utils import fmt_rub, kopecks_to_str, normalize_player_id, str_to_kopecks, valid_email
from .yookassa import YooKassa, YooKassaError

log = logging.getLogger("orders")
settings = get_settings()
yk = YooKassa(settings.yookassa_shop_id, settings.yookassa_secret_key)
supplier = get_supplier(settings.supplier)

STATUS_TEXT = {
    Status.PENDING: "⏳ Ожидает оплаты",
    Status.PAID: "💳 Оплачен, начисляем UC",
    Status.DELIVERED: "✅ UC начислены",
    Status.CANCELED: "✖️ Отменён",
    Status.REFUNDED: "↩️ Деньги возвращены",
}


class ShopError(Exception):
    """Ошибка, текст которой можно показать пользователю."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


# ───────────────────────── пользователи ─────────────────────────


async def upsert_user(session, tg_user: dict) -> User:
    uid = int(tg_user["id"])
    username = tg_user.get("username")
    first_name = tg_user.get("first_name")
    user = await session.get(User, uid)
    if user is None:
        user = User(id=uid, username=username, first_name=first_name)
        session.add(user)
        try:
            await session.flush()
        except IntegrityError:  # параллельный запрос создал пользователя первым
            await session.rollback()
            user = await session.get(User, uid)
    else:
        user.username, user.first_name = username, first_name
    return user


async def touch_user(tg_user: dict) -> User:
    async with SessionLocal() as s:
        user = await upsert_user(s, tg_user)
        await s.commit()
        return user


# ───────────────────────── создание заказа ─────────────────────────


def _receipt(order: Order) -> dict | None:
    if not settings.receipt_enabled:
        return None
    receipt: dict = {
        "customer": {"email": order.email},
        "items": [
            {
                "description": f"PUBG Mobile {order.uc} UC",
                "quantity": "1.00",
                "amount": {"value": kopecks_to_str(order.price), "currency": "RUB"},
                "vat_code": settings.receipt_vat_code,
                "payment_mode": settings.receipt_payment_mode,
                "payment_subject": settings.receipt_payment_subject,
            }
        ],
    }
    if settings.receipt_tax_system_code:
        receipt["tax_system_code"] = settings.receipt_tax_system_code
    return receipt


async def create_order(tg_user: dict, product_id: int, player_id_raw: str, email: str | None) -> Order:
    player_id = normalize_player_id(player_id_raw)
    if not player_id:
        raise ShopError("Неверный Player ID. Это 8–12 цифр, найти его можно в профиле игры.")
    email = (email or "").strip() or None
    if settings.receipt_enabled and not valid_email(email):
        raise ShopError("Укажите корректный email — на него придёт чек.")
    if email and not valid_email(email):
        raise ShopError("Некорректный email.")

    async with SessionLocal() as s:
        user = await upsert_user(s, tg_user)
        if user.is_banned:
            raise ShopError("Доступ к магазину ограничен.")
        product = await s.get(Product, product_id)
        if product is None or not product.active or product.price <= 0:
            raise ShopError("Этот пакет сейчас недоступен.")

        cutoff = utcnow() - timedelta(minutes=settings.order_ttl_minutes)
        pending = await s.scalar(
            select(func.count())
            .select_from(Order)
            .where(Order.user_id == user.id, Order.status == Status.PENDING, Order.created_at > cutoff)
        )
        if pending >= settings.max_pending_orders:
            raise ShopError("Слишком много неоплаченных заказов. Оплатите или дождитесь их отмены.")

        order = Order(
            id=uuid4().hex,
            user_id=user.id,
            product_id=product.id,
            uc=product.uc,
            price=product.price,
            cost=product.cost,
            player_id=player_id,
            email=email,
        )
        s.add(order)
        await s.commit()

    try:
        payment = await yk.create_payment(
            order_id=order.id,
            amount_kopecks=order.price,
            description=f"PUBG Mobile {order.uc} UC · заказ {order.short}",
            return_url=f"https://t.me/{settings.bot_username}?start=o_{order.id}",
            receipt=_receipt(order),
        )
        url = payment["confirmation"]["confirmation_url"]
        payment_id = payment["id"]
    except (YooKassaError, KeyError):
        log.exception("payment creation failed for order %s", order.id)
        async with SessionLocal() as s:
            await s.execute(
                update(Order).where(Order.id == order.id).values(status=Status.CANCELED, note="payment create failed")
            )
            await s.commit()
        raise ShopError("Не удалось создать платёж. Попробуйте ещё раз через минуту.") from None

    async with SessionLocal() as s:
        await s.execute(update(Order).where(Order.id == order.id).values(payment_id=payment_id, payment_url=url))
        await s.commit()
    order.payment_id, order.payment_url = payment_id, url
    return order


# ───────────────────────── оплата ─────────────────────────


async def confirm_payment(payment_id: str) -> None:
    """Источник истины — сам ЮKassa: статус всегда перепроверяется запросом к API,
    поэтому подделанный вебхук ничего не даст."""
    payment = await yk.get_payment(payment_id)
    order_id = (payment.get("metadata") or {}).get("order_id")
    if not order_id:
        return
    status = payment.get("status")
    became_paid = False

    async with SessionLocal() as s:
        order = await s.get(Order, order_id)
        if order is None or order.payment_id != payment_id:
            log.warning("payment %s does not match any order", payment_id)
            return

        if status == "succeeded" and payment.get("paid"):
            amount = payment.get("amount") or {}
            if amount.get("currency") != "RUB" or str_to_kopecks(amount.get("value", "0")) != order.price:
                order.note = f"amount mismatch: {amount}"
                await s.commit()
                log.error("amount mismatch for order %s: %s", order.id, amount)
                await notify.notify_admins(f"⚠️ Сумма платежа не совпала с заказом <b>#{order.short}</b>. Проверьте вручную.")
                return
            # CANCELED тоже допустим: клиент мог оплатить уже после нашей отмены по таймеру.
            res = await s.execute(
                update(Order)
                .where(Order.id == order_id, Order.status.in_((Status.PENDING, Status.CANCELED)))
                .values(status=Status.PAID, paid_at=utcnow())
            )
            await s.commit()
            became_paid = res.rowcount == 1
        elif status == "canceled":
            reason = (payment.get("cancellation_details") or {}).get("reason", "")
            await s.execute(
                update(Order)
                .where(Order.id == order_id, Order.status == Status.PENDING)
                .values(status=Status.CANCELED, note=f"payment canceled {reason}".strip())
            )
            await s.commit()

    if became_paid:
        await _after_paid(order_id)


async def _after_paid(order_id: str) -> None:
    async with SessionLocal() as s:
        order = await s.get(Order, order_id)
        user = await s.get(User, order.user_id)

    await notify.send(
        order.user_id,
        f"💳 Оплата получена. Заказ <b>#{order.short}</b>: {order.uc} UC.\n"
        f"Начисляем на Player ID <code>{order.player_id}</code> — {settings.delivery_eta_text}.",
    )
    try:
        result = await supplier.deliver(order, user)
    except Exception:
        log.exception("supplier failed for order %s", order_id)
        result = DeliveryResult("failed", "exception")

    if result.status == "delivered":
        await mark_delivered(order_id)
    elif result.status == "failed":
        await notify.notify_admins(
            f"⚠️ Не удалось выдать заказ <b>#{order.short}</b> автоматически ({result.note}).",
            notify.admin_order_kb(order_id),
        )


async def mark_delivered(order_id: str) -> bool:
    async with SessionLocal() as s:
        res = await s.execute(
            update(Order)
            .where(Order.id == order_id, Order.status == Status.PAID)
            .values(status=Status.DELIVERED, delivered_at=utcnow())
        )
        await s.commit()
        if res.rowcount != 1:
            return False
        order = await s.get(Order, order_id)
    await notify.send(
        order.user_id,
        f"✅ Заказ <b>#{order.short}</b> выполнен: {order.uc} UC начислены на ID <code>{order.player_id}</code>.\n"
        "Приятной игры! Если что-то не так — напишите в поддержку.",
    )
    return True


async def refund_order(order_id: str) -> tuple[bool, str]:
    async with SessionLocal() as s:
        order = await s.get(Order, order_id)
    if order is None:
        return False, "Заказ не найден"
    if order.status != Status.PAID or not order.payment_id:
        return False, f"Возврат невозможен: {STATUS_TEXT.get(order.status, order.status)}"
    try:
        result = await yk.refund(
            order_id=order.id,
            payment_id=order.payment_id,
            amount_kopecks=order.price,
            receipt=_receipt(order),
        )
    except YooKassaError as exc:
        return False, f"ЮKassa отклонила запрос: {exc}"
    if result.get("status") == "canceled":
        return False, "ЮKassa отменила возврат"

    async with SessionLocal() as s:
        res = await s.execute(
            update(Order)
            .where(Order.id == order_id, Order.status == Status.PAID)
            .values(status=Status.REFUNDED, refunded_at=utcnow())
        )
        await s.commit()
    if res.rowcount == 1:
        await notify.send(
            order.user_id,
            f"↩️ По заказу <b>#{order.short}</b> оформлен возврат {fmt_rub(order.price)}. "
            "Деньги вернутся на карту в течение нескольких дней.",
        )
    return True, f"Возврат {fmt_rub(order.price)} оформлен"


# ───────────────────────── сверка (страховка от потерянных вебхуков) ─────────────────────────


async def reconcile_once() -> None:
    now = utcnow()
    async with SessionLocal() as s:
        pending = (
            await s.scalars(
                select(Order)
                .where(
                    Order.status == Status.PENDING,
                    Order.payment_id.is_not(None),
                    Order.created_at < now - timedelta(seconds=30),
                )
                .order_by(Order.created_at)
                .limit(100)
            )
        ).all()
    for order in pending:
        try:
            await confirm_payment(order.payment_id)
        except Exception:
            log.exception("reconcile failed for order %s", order.id)

    cutoff = now - timedelta(minutes=settings.order_ttl_minutes)
    async with SessionLocal() as s:
        await s.execute(
            update(Order)
            .where(Order.status == Status.PENDING, Order.created_at < cutoff)
            .values(status=Status.CANCELED, note="expired")
        )
        await s.commit()


async def reconcile_loop() -> None:
    while True:
        try:
            await reconcile_once()
        except Exception:
            log.exception("reconcile loop error")
        await asyncio.sleep(60)


# ───────────────────────── выборки для бота и API ─────────────────────────


async def user_orders(user_id: int, limit: int = 20) -> list[Order]:
    async with SessionLocal() as s:
        rows = await s.scalars(
            select(Order).where(Order.user_id == user_id).order_by(Order.created_at.desc()).limit(limit)
        )
        return list(rows)


async def get_user_order(user_id: int, order_id: str) -> Order | None:
    async with SessionLocal() as s:
        order = await s.get(Order, order_id)
        return order if order and order.user_id == user_id else None


async def find_order(prefix: str) -> Order | None:
    prefix = prefix.strip().lower().lstrip("#")
    if len(prefix) < 4:
        return None
    async with SessionLocal() as s:
        return await s.scalar(select(Order).where(Order.id.like(f"{prefix}%")).limit(1))


async def set_banned(user_id: int, banned: bool) -> bool:
    async with SessionLocal() as s:
        res = await s.execute(update(User).where(User.id == user_id).values(is_banned=banned))
        await s.commit()
        return res.rowcount == 1


async def awaiting_delivery() -> list[Order]:
    async with SessionLocal() as s:
        rows = await s.scalars(select(Order).where(Order.status == Status.PAID).order_by(Order.paid_at))
        return list(rows)


async def stats() -> dict:
    tz = ZoneInfo(settings.timezone)
    now_local = datetime.now(tz)
    midnight = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    periods = {
        "Сегодня": midnight,
        "7 дней": midnight - timedelta(days=6),
        "30 дней": midnight - timedelta(days=29),
        "Всё время": None,
    }
    out: dict = {"periods": {}}
    async with SessionLocal() as s:
        for name, since in periods.items():
            q = select(
                func.count(),
                func.coalesce(func.sum(Order.price), 0),
                func.coalesce(func.sum(Order.price - Order.cost), 0),
                func.coalesce(func.sum(Order.uc), 0),
            ).where(Order.status.in_((Status.PAID, Status.DELIVERED)))
            if since is not None:
                q = q.where(Order.paid_at >= since.astimezone(ZoneInfo("UTC")))
            count, revenue, profit, uc = (await s.execute(q)).one()
            out["periods"][name] = {"count": count, "revenue": int(revenue), "profit": int(profit), "uc": int(uc)}
        out["awaiting"] = await s.scalar(select(func.count()).select_from(Order).where(Order.status == Status.PAID))
        out["pending"] = await s.scalar(select(func.count()).select_from(Order).where(Order.status == Status.PENDING))
    return out
