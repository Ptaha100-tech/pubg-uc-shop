from datetime import datetime, timezone

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Status:
    PENDING = "pending"  # ждём оплату
    PAID = "paid"  # оплачен, UC ещё не выданы
    DELIVERED = "delivered"  # UC выданы
    CANCELED = "canceled"  # не оплачен / отменён
    REFUNDED = "refunded"  # деньги возвращены

    ALL = (PENDING, PAID, DELIVERED, CANCELED, REFUNDED)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    username: Mapped[str | None] = mapped_column(String(64))
    first_name: Mapped[str | None] = mapped_column(String(128))
    is_banned: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Product(Base):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    uc: Mapped[int] = mapped_column(Integer, unique=True)
    title: Mapped[str] = mapped_column(String(64))
    price: Mapped[int] = mapped_column(Integer)  # копейки
    cost: Mapped[int] = mapped_column(Integer, default=0)  # закупка, копейки
    old_price: Mapped[int] = mapped_column(Integer, default=0)  # зачёркнутая цена, копейки (0 = не показывать)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    sort: Mapped[int] = mapped_column(Integer, default=0)


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), index=True)
    product_id: Mapped[int] = mapped_column(Integer, ForeignKey("products.id"))
    uc: Mapped[int] = mapped_column(Integer)  # снимок на момент заказа
    price: Mapped[int] = mapped_column(Integer)  # копейки, снимок
    cost: Mapped[int] = mapped_column(Integer, default=0)  # копейки, снимок
    player_id: Mapped[str] = mapped_column(String(16))
    email: Mapped[str | None] = mapped_column(String(254))
    status: Mapped[str] = mapped_column(String(16), default=Status.PENDING, index=True)
    payment_id: Mapped[str | None] = mapped_column(String(64), unique=True)
    payment_url: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    refunded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    note: Mapped[str | None] = mapped_column(Text)

    @property
    def short(self) -> str:
        return self.id[:8].upper()
