import asyncio
import hmac
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from aiogram.types import (
    BotCommand,
    BotCommandScopeChat,
    MenuButtonWebApp,
    Update,
    WebAppInfo,
)
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from . import orders
from .api import router as api_router
from .bot import bot, dp
from .catalog import seed_products
from .config import get_settings
from .db import init_db
from .handlers import admin as admin_router
from .handlers import router as user_router

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("main")
settings = get_settings()

WEB_DIR = Path(__file__).resolve().parent.parent / "web"

dp.include_router(admin_router)
dp.include_router(user_router)

BOT_DESCRIPTION = (
    "🪙 Магазин UC для PUBG Mobile\n\n"
    "⚡️ Быстрое пополнение по Player ID\n"
    "💳 Оплата через ЮKassa\n"
    "🛡 Пароль от аккаунта не нужен\n\n"
    "Нажмите «Начать», чтобы открыть магазин."
)
BOT_SHORT_DESCRIPTION = "UC для PUBG Mobile по ID: быстро, без пароля от аккаунта."

USER_COMMANDS = [
    BotCommand(command="start", description="Открыть магазин"),
    BotCommand(command="orders", description="Мои заказы"),
    BotCommand(command="help", description="Как найти Player ID"),
    BotCommand(command="support", description="Поддержка"),
]
ADMIN_COMMANDS = USER_COMMANDS + [
    BotCommand(command="admin", description="Команды админа"),
    BotCommand(command="stats", description="Статистика"),
    BotCommand(command="pending", description="Ждут выдачи"),
    BotCommand(command="products", description="Пакеты и цены"),
]


@asynccontextmanager
async def lifespan(_: FastAPI):
    await init_db()
    await seed_products()

    await bot.set_webhook(
        url=f"{settings.base_url}/tg/webhook",
        secret_token=settings.webhook_secret,
        allowed_updates=dp.resolve_used_update_types(),
    )
    await bot.set_chat_menu_button(
        menu_button=MenuButtonWebApp(text="Купить UC", web_app=WebAppInfo(url=f"{settings.base_url}/app/"))
    )
    await bot.set_my_commands(USER_COMMANDS)
    try:
        await bot.set_my_description(description=BOT_DESCRIPTION)
        await bot.set_my_short_description(short_description=BOT_SHORT_DESCRIPTION)
    except Exception:
        log.warning("cannot set bot description", exc_info=True)
    for admin_id in settings.admin_id_list:
        try:
            await bot.set_my_commands(ADMIN_COMMANDS, scope=BotCommandScopeChat(chat_id=admin_id))
        except Exception:  # админ ещё не нажимал /start у бота
            log.warning("cannot set admin commands for %s (press /start in the bot)", admin_id)

    task = asyncio.create_task(orders.reconcile_loop())
    log.info("started, webhook=%s/tg/webhook", settings.base_url)
    try:
        yield
    finally:
        task.cancel()
        await orders.yk.aclose()
        await bot.session.close()


app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
app.include_router(api_router)


@app.post("/tg/webhook")
async def telegram_webhook(
    request: Request,
    x_telegram_bot_api_secret_token: str = Header(default=""),
) -> dict:
    if not hmac.compare_digest(x_telegram_bot_api_secret_token, settings.webhook_secret):
        raise HTTPException(403)
    try:
        update = Update.model_validate(await request.json(), context={"bot": bot})
        await dp.feed_update(bot, update)
    except Exception:
        # Всегда отвечаем 200, иначе Telegram будет бесконечно переотправлять сбойный апдейт.
        log.exception("update handling failed")
    return {"ok": True}


@app.get("/health")
async def health() -> dict:
    return {"ok": True}


@app.get("/", include_in_schema=False)
async def root() -> RedirectResponse:
    return RedirectResponse("/app/")


app.mount("/app", StaticFiles(directory=WEB_DIR, html=True), name="web")
