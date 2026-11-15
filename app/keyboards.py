"""Клавиатуры бота (вынесены отдельно, чтобы их мог использовать и модуль заказов)."""
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo

from .config import get_settings

settings = get_settings()


def shop_button(text: str = "🛒 Купить UC") -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, web_app=WebAppInfo(url=f"{settings.base_url}/app/"))


def shop_kb(text: str = "🛒 Купить UC") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[shop_button(text)]])


def support_button() -> InlineKeyboardButton:
    if settings.support_username:
        return InlineKeyboardButton(text="💬 Поддержка", url=f"https://t.me/{settings.support_username}")
    return InlineKeyboardButton(text="💬 Поддержка", callback_data="support")


def main_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [shop_button()],
            [
                InlineKeyboardButton(text="📦 Мои заказы", callback_data="orders"),
                InlineKeyboardButton(text="🆔 Где найти ID", callback_data="howid"),
            ],
            [support_button()],
        ]
    )


def back_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[shop_button()], [support_button()]])
