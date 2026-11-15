from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Telegram
    bot_token: str
    bot_username: str  # без @
    public_url: str  # https://shop.example.com (без слеша в конце)
    webhook_secret: str  # A-Za-z0-9_- , до 256 символов
    admin_ids: str = ""  # Telegram ID админов через запятую
    admin_chat_id: int | None = None  # чат/группа для заказов; иначе пишем каждому админу
    support_username: str = ""  # без @, показывается в Mini App

    # База
    database_url: str = "sqlite+aiosqlite:///./shop.db"

    # ЮKassa
    yookassa_shop_id: str
    yookassa_secret_key: str

    # Чеки 54-ФЗ (если ЮKassa настроена на отправку чеков)
    receipt_enabled: bool = False
    receipt_vat_code: int = 1  # 1 = без НДС
    receipt_tax_system_code: int | None = None
    receipt_payment_subject: str = "service"
    receipt_payment_mode: str = "full_payment"

    # Заказы
    order_ttl_minutes: int = 70  # >= срока жизни платежа в ЮKassa (60 мин)
    max_pending_orders: int = 5
    supplier: str = "manual"
    delivery_eta_text: str = "обычно до 15 минут"
    timezone: str = "Europe/Moscow"  # для статистики «за сегодня»

    @property
    def admin_id_list(self) -> list[int]:
        return [int(x) for x in self.admin_ids.replace(" ", "").split(",") if x]

    @property
    def base_url(self) -> str:
        return self.public_url.rstrip("/")


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
