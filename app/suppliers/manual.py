from .. import notify
from ..models import Order, User
from . import DeliveryResult, Supplier


class ManualSupplier(Supplier):
    """Заказ уходит админу в Telegram, UC выдаются вручную, затем кнопка «Выдано»."""

    name = "manual"

    async def deliver(self, order: Order, user: User | None) -> DeliveryResult:
        await notify.admin_new_paid(order, user)
        return DeliveryResult("queued", "sent to admins")
