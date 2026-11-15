"""Модуль поставщика UC.

Чтобы подключить автоматическую выдачу, создайте класс-наследник Supplier,
реализуйте `deliver` и добавьте его в `get_supplier`. Тогда SUPPLIER=<имя> в .env
переключит магазин на авто-выдачу, остальной код трогать не нужно.

Результат deliver:
  delivered — UC начислены прямо сейчас (заказ закроется автоматически);
  queued    — принято в работу, выдача подтвердится позже (например, вручную);
  failed    — ошибка поставщика: заказ остаётся «оплачен», админ получает алерт.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Literal

from ..models import Order, User


@dataclass
class DeliveryResult:
    status: Literal["delivered", "queued", "failed"]
    note: str = ""


class Supplier(ABC):
    name: str

    @abstractmethod
    async def deliver(self, order: Order, user: User | None) -> DeliveryResult: ...


def get_supplier(name: str) -> Supplier:
    from .manual import ManualSupplier

    registry: dict[str, type[Supplier]] = {"manual": ManualSupplier}
    try:
        return registry[name]()
    except KeyError:
        raise RuntimeError(f"Неизвестный SUPPLIER={name!r}. Доступно: {', '.join(registry)}") from None
