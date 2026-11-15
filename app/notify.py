import logging
from html import escape

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from .bot import bot
from .config import get_settings
from .models import Order, User
from .utils import fmt_rub

log = logging.getLogger("notify")
settings = get_settings()


async def send(chat_id: int, text: str, reply_markup: InlineKeyboardMarkup | None = None) -> None:
    try:
        await bot.send_message(chat_id, text, reply_markup=reply_markup)
    except Exception:  # пользователь мог заблокировать бота — это не должно ломать заказ
        log.warning("cannot send message to %s", chat_id, exc_info=True)


async def notify_admins(text: str, reply_markup: InlineKeyboardMarkup | None = None) -> None:
    targets = [settings.admin_chat_id] if settings.admin_chat_id else settings.admin_id_list
    for chat_id in targets:
        await send(chat_id, text, reply_markup)


def admin_order_kb(order_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Выдано", callback_data=f"dlv:{order_id}"),
                InlineKeyboardButton(text="↩️ Возврат", callback_data=f"rfd:{order_id}"),
            ]
        ]
    )


def user_label(user: User | None, user_id: int) -> str:
    if user is None:
        return f"id {user_id}"
    name = f"@{escape(user.username)}" if user.username else escape(user.first_name or "—")
    return f'<a href="tg://user?id={user_id}">{name}</a> (id <code>{user_id}</code>)'


def admin_order_text(order: Order, user: User | None, title: str) -> str:
    profit = order.price - order.cost
    return (
        f"{title} <b>#{order.short}</b>\n"
        f"Пакет: <b>{order.uc} UC</b>\n"
        f"Player ID: <code>{escape(order.player_id)}</code>\n"
        f"Оплачено: {fmt_rub(order.price)} · закупка {fmt_rub(order.cost)} · прибыль {fmt_rub(profit)}\n"
        f"Покупатель: {user_label(user, order.user_id)}"
    )


async def admin_new_paid(order: Order, user: User | None) -> None:
    await notify_admins(admin_order_text(order, user, "💳 Оплачен заказ"), admin_order_kb(order.id))
