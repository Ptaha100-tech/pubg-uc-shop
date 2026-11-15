import logging
from html import escape
from pathlib import Path

from aiogram import F, Router
from aiogram.filters import BaseFilter, Command, CommandObject, CommandStart
from aiogram.types import (
    CallbackQuery,
    FSInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from . import catalog, keyboards, notify, orders
from .config import get_settings
from .models import Status
from .orders import STATUS_TEXT
from .utils import fmt_rub, parse_rub

log = logging.getLogger("handlers")
settings = get_settings()

IMG_DIR = Path(__file__).resolve().parent.parent / "web" / "img"
HERO_VIDEO = IMG_DIR / "hero.mp4"
BANNER = IMG_DIR / "banner.jpg"
# После первой отправки Telegram хранит файл у себя, дальше шлём по file_id (быстро, без нагрузки на сервер)
_media_ids: dict[str, str] = {}

router = Router(name="user")
admin = Router(name="admin")
router.message.filter(lambda m: m.chat.type == "private")


class IsAdmin(BaseFilter):
    async def __call__(self, event: Message | CallbackQuery) -> bool:
        return event.from_user is not None and event.from_user.id in settings.admin_id_list


admin.message.filter(IsAdmin())
admin.callback_query.filter(IsAdmin())


def tg_dict(m: Message) -> dict:
    u = m.from_user
    return {"id": u.id, "username": u.username, "first_name": u.first_name}


def order_card(o) -> str:
    return (
        f"📦 <b>Заказ #{o.short}</b>\n"
        f"🪙 {o.uc} UC · {fmt_rub(o.price)}\n"
        f"🆔 <code>{escape(o.player_id)}</code>\n"
        f"{STATUS_TEXT.get(o.status, o.status)}"
    )


def welcome_text() -> str:
    return (
        f"🪙 <b>{escape(settings.shop_name)}</b>\n"
        "Пополнение <b>UC для PUBG Mobile</b> по ID\n\n"
        "1️⃣ Выберите пакет UC\n"
        "2️⃣ Введите Player ID\n"
        "3️⃣ Оплатите заказ\n"
        f"4️⃣ UC придут на аккаунт — {escape(settings.delivery_eta_text)}\n\n"
        "🛡 Пароль от аккаунта нам <b>не нужен</b> — только ID игрока."
    )


HOWID_TEXT = (
    "🆔 <b>Где найти Player ID</b>\n\n"
    "1. Откройте PUBG Mobile\n"
    "2. Нажмите на свой аватар в левом верхнем углу\n"
    "3. Под ником указан <b>ID персонажа</b> — 8–12 цифр\n"
    "4. Скопируйте его и вставьте при оформлении заказа\n\n"
    "⚠️ После начисления вернуть UC нельзя, поэтому проверяйте ID перед оплатой."
)


def support_text() -> str:
    contact = f"@{settings.support_username}" if settings.support_username else "администратору магазина"
    return (
        "💬 <b>Поддержка</b>\n\n"
        f"По вопросам оплаты и начисления UC пишите {contact}.\n"
        "Укажите номер заказа — он виден в разделе «Мои заказы».\n\n"
        "↩️ Если заказ оплачен, но UC ещё не начислены, мы вернём деньги по вашему запросу."
    )


async def send_welcome(m: Message) -> None:
    caption, kb = welcome_text(), keyboards.main_kb()
    if HERO_VIDEO.exists():
        try:
            sent = await m.answer_animation(
                _media_ids.get("video") or FSInputFile(HERO_VIDEO), caption=caption, reply_markup=kb
            )
            media = sent.animation or sent.video
            if media:
                _media_ids["video"] = media.file_id
            return
        except Exception:  # не получилось с видео — пробуем картинку
            _media_ids.pop("video", None)
            log.warning("cannot send welcome video", exc_info=True)
    if BANNER.exists():
        try:
            sent = await m.answer_photo(_media_ids.get("photo") or FSInputFile(BANNER), caption=caption, reply_markup=kb)
            if sent.photo:
                _media_ids["photo"] = sent.photo[-1].file_id
            return
        except Exception:  # и с картинкой не вышло — обычный текст
            _media_ids.pop("photo", None)
            log.warning("cannot send welcome photo", exc_info=True)
    await m.answer(caption, reply_markup=kb)


async def send_orders(m: Message, user_id: int) -> None:
    rows = await orders.user_orders(user_id, limit=10)
    if not rows:
        await m.answer("📦 Заказов пока нет.\nВыберите пакет UC в магазине 👇", reply_markup=keyboards.shop_kb())
        return
    await m.answer(
        "📦 <b>Мои заказы</b>\n\n" + "\n\n".join(order_card(o) for o in rows),
        reply_markup=keyboards.shop_kb(),
    )


# ───────────────────────── пользователи ─────────────────────────


@router.message(CommandStart())
async def cmd_start(m: Message, command: CommandObject) -> None:
    await orders.touch_user(tg_dict(m))
    if command.args and command.args.startswith("o_"):
        order = await orders.get_user_order(m.from_user.id, command.args[2:])
        if order:
            await m.answer(order_card(order), reply_markup=keyboards.main_kb())
            return
    await send_welcome(m)


@router.message(Command("orders"))
async def cmd_orders(m: Message) -> None:
    await send_orders(m, m.from_user.id)


@router.message(Command("help"))
async def cmd_help(m: Message) -> None:
    await m.answer(HOWID_TEXT, reply_markup=keyboards.back_kb())


@router.message(Command("support", "paysupport"))
async def cmd_support(m: Message) -> None:
    await m.answer(support_text(), reply_markup=keyboards.shop_kb())


@router.callback_query(F.data == "orders")
async def cb_orders(c: CallbackQuery) -> None:
    await c.answer()
    if isinstance(c.message, Message):
        await send_orders(c.message, c.from_user.id)


@router.callback_query(F.data == "howid")
async def cb_howid(c: CallbackQuery) -> None:
    await c.answer()
    if isinstance(c.message, Message):
        await c.message.answer(HOWID_TEXT, reply_markup=keyboards.back_kb())


@router.callback_query(F.data == "support")
async def cb_support(c: CallbackQuery) -> None:
    await c.answer()
    if isinstance(c.message, Message):
        await c.message.answer(support_text(), reply_markup=keyboards.shop_kb())


# ───────────────────────── админ ─────────────────────────

ADMIN_HELP = (
    "<b>Команды админа</b>\n"
    "/stats — выручка и прибыль\n"
    "/pending — оплаченные, но не выданные заказы\n"
    "/order &lt;номер&gt; — найти заказ\n"
    "/products — пакеты и цены\n"
    "/price &lt;UC&gt; &lt;₽&gt; — цена продажи\n"
    "/cost &lt;UC&gt; &lt;₽&gt; — закупочная цена\n"
    "/oldprice &lt;UC&gt; &lt;₽&gt; — зачёркнутая цена (0 — убрать). Только реально действовавшая!\n"
    "/toggle &lt;UC&gt; — включить/выключить пакет\n"
    "/addpack &lt;UC&gt; &lt;₽&gt; [закупка ₽] — новый пакет\n"
    "/ban &lt;id&gt; · /unban &lt;id&gt; — блокировка покупателя"
)


@admin.message(Command("admin"))
async def adm_help(m: Message) -> None:
    await m.answer(ADMIN_HELP)


@admin.message(Command("stats"))
async def adm_stats(m: Message) -> None:
    st = await orders.stats()
    lines = ["<b>📊 Статистика</b>"]
    for name, p in st["periods"].items():
        lines.append(
            f"\n<b>{name}</b>: {p['count']} заказов, {p['uc']} UC\n"
            f"выручка {fmt_rub(p['revenue'])} · прибыль {fmt_rub(p['profit'])}"
        )
    lines.append(f"\nЖдут выдачи: <b>{st['awaiting']}</b> · ждут оплаты: {st['pending']}")
    await m.answer("\n".join(lines))


@admin.message(Command("products"))
async def adm_products(m: Message) -> None:
    rows = await catalog.list_all()
    lines = ["<b>Пакеты</b> (UC · цена · закупка · маржа)"]
    for p in rows:
        mark = "🟢" if p.active else "⚪️"
        old = f" · было {fmt_rub(p.old_price)}" if p.old_price > p.price else ""
        lines.append(f"{mark} {p.uc} UC · {fmt_rub(p.price)} · {fmt_rub(p.cost)} · {fmt_rub(p.price - p.cost)}{old}")
    await m.answer("\n".join(lines))


async def _price_like(m: Message, command: CommandObject, setter, label: str) -> None:
    try:
        uc_s, rub_s = (command.args or "").split()
        uc, kop = int(uc_s), parse_rub(rub_s)
    except ValueError:
        await m.answer(f"Формат: /{command.command} &lt;UC&gt; &lt;₽&gt;, например /{command.command} 325 299")
        return
    if await setter(uc, kop):
        await m.answer(f"{label} для {uc} UC: <b>{fmt_rub(kop)}</b>")
    else:
        await m.answer("Такого пакета нет. Добавить: /addpack")


@admin.message(Command("price"))
async def adm_price(m: Message, command: CommandObject) -> None:
    await _price_like(m, command, catalog.set_price, "Цена")


@admin.message(Command("cost"))
async def adm_cost(m: Message, command: CommandObject) -> None:
    await _price_like(m, command, catalog.set_cost, "Закупка")


@admin.message(Command("oldprice"))
async def adm_oldprice(m: Message, command: CommandObject) -> None:
    await _price_like(m, command, catalog.set_old_price, "Зачёркнутая цена")


@admin.message(Command("toggle"))
async def adm_toggle(m: Message, command: CommandObject) -> None:
    try:
        uc = int((command.args or "").strip())
    except ValueError:
        await m.answer("Формат: /toggle 325")
        return
    ok, text = await catalog.toggle(uc)
    await m.answer(f"{uc} UC {text}" if ok else text)


@admin.message(Command("addpack"))
async def adm_addpack(m: Message, command: CommandObject) -> None:
    parts = (command.args or "").split()
    try:
        uc, price = int(parts[0]), parse_rub(parts[1])
        cost = parse_rub(parts[2]) if len(parts) > 2 else 0
    except (ValueError, IndexError):
        await m.answer("Формат: /addpack &lt;UC&gt; &lt;₽&gt; [закупка ₽], например /addpack 2460 1990 1850")
        return
    await m.answer("Пакет добавлен" if await catalog.add_pack(uc, price, cost) else "Такой пакет уже есть")


@admin.message(Command("pending"))
async def adm_pending(m: Message) -> None:
    rows = await orders.awaiting_delivery()
    if not rows:
        await m.answer("Все оплаченные заказы выданы ✅")
        return
    for o in rows:
        await m.answer(notify.admin_order_text(o, None, "💳 Ждёт выдачи"), reply_markup=notify.admin_order_kb(o.id))


@admin.message(Command("order"))
async def adm_order(m: Message, command: CommandObject) -> None:
    o = await orders.find_order(command.args or "")
    if not o:
        await m.answer("Не найден. Формат: /order ABC12345")
        return
    kb = notify.admin_order_kb(o.id) if o.status == Status.PAID else None
    await m.answer(notify.admin_order_text(o, None, f"{STATUS_TEXT.get(o.status)}\nЗаказ"), reply_markup=kb)


async def _ban(m: Message, command: CommandObject, banned: bool) -> None:
    try:
        uid = int((command.args or "").strip())
    except ValueError:
        await m.answer(f"Формат: /{command.command} 123456789")
        return
    await m.answer("Готово" if await orders.set_banned(uid, banned) else "Пользователь не найден")


@admin.message(Command("ban"))
async def adm_ban(m: Message, command: CommandObject) -> None:
    await _ban(m, command, True)


@admin.message(Command("unban"))
async def adm_unban(m: Message, command: CommandObject) -> None:
    await _ban(m, command, False)


# ───────────────────────── кнопки под заказом ─────────────────────────


async def _finish(c: CallbackQuery, suffix: str) -> None:
    if isinstance(c.message, Message):
        who = f"@{c.from_user.username}" if c.from_user.username else str(c.from_user.id)
        await c.message.edit_text(f"{c.message.html_text}\n\n{suffix} ({escape(who)})", reply_markup=None)


@admin.callback_query(F.data.startswith("dlv:"))
async def cb_deliver(c: CallbackQuery) -> None:
    ok = await orders.mark_delivered(c.data[4:])
    await c.answer("Отмечено, клиент уведомлён" if ok else "Заказ уже обработан", show_alert=not ok)
    if ok:
        await _finish(c, "✅ Выдано")


@admin.callback_query(F.data.startswith("rfd:"))
async def cb_refund_ask(c: CallbackQuery) -> None:
    order_id = c.data[4:]
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Да, вернуть деньги", callback_data=f"rfy:{order_id}"),
                InlineKeyboardButton(text="Отмена", callback_data=f"rfn:{order_id}"),
            ]
        ]
    )
    await c.answer()
    if isinstance(c.message, Message):
        await c.message.edit_reply_markup(reply_markup=kb)


@admin.callback_query(F.data.startswith("rfn:"))
async def cb_refund_cancel(c: CallbackQuery) -> None:
    await c.answer()
    if isinstance(c.message, Message):
        await c.message.edit_reply_markup(reply_markup=notify.admin_order_kb(c.data[4:]))


@admin.callback_query(F.data.startswith("rfy:"))
async def cb_refund_confirm(c: CallbackQuery) -> None:
    ok, text = await orders.refund_order(c.data[4:])
    await c.answer(text, show_alert=True)
    if ok:
        await _finish(c, "↩️ Возврат")
    elif isinstance(c.message, Message):
        await c.message.edit_reply_markup(reply_markup=notify.admin_order_kb(c.data[4:]))


# ───────────────────────── всё остальное ─────────────────────────
# Должен стоять последним: ловит обычный текст, который не является командой.


@router.message(F.text & ~F.text.startswith("/"))
async def fallback(m: Message) -> None:
    await m.answer("Выберите действие 👇", reply_markup=keyboards.main_kb())
