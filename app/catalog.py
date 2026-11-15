from sqlalchemy import select

from .db import SessionLocal
from .models import Product

# Официальные номиналы UC в PUBG Mobile. Цены задаются вами через бота (/price),
# поэтому пакеты создаются выключенными с нулевой ценой: случайно продать нечего.
DEFAULT_PACKS = [60, 325, 660, 1800, 3850, 8100]


async def seed_products() -> None:
    async with SessionLocal() as s:
        if await s.scalar(select(Product.id).limit(1)) is not None:
            return
        for i, uc in enumerate(DEFAULT_PACKS):
            s.add(Product(uc=uc, title=f"{uc} UC", price=0, cost=0, active=False, sort=i))
        await s.commit()


async def list_active() -> list[Product]:
    async with SessionLocal() as s:
        rows = await s.scalars(
            select(Product).where(Product.active.is_(True), Product.price > 0).order_by(Product.sort, Product.uc)
        )
        return list(rows)


async def list_all() -> list[Product]:
    async with SessionLocal() as s:
        return list(await s.scalars(select(Product).order_by(Product.sort, Product.uc)))


async def get_by_uc(uc: int) -> Product | None:
    async with SessionLocal() as s:
        return await s.scalar(select(Product).where(Product.uc == uc))


async def set_price(uc: int, kopecks: int) -> bool:
    async with SessionLocal() as s:
        p = await s.scalar(select(Product).where(Product.uc == uc))
        if p is None:
            return False
        p.price = kopecks
        if kopecks <= 0:
            p.active = False
        await s.commit()
        return True


async def set_cost(uc: int, kopecks: int) -> bool:
    async with SessionLocal() as s:
        p = await s.scalar(select(Product).where(Product.uc == uc))
        if p is None:
            return False
        p.cost = kopecks
        await s.commit()
        return True


async def toggle(uc: int) -> tuple[bool, str]:
    async with SessionLocal() as s:
        p = await s.scalar(select(Product).where(Product.uc == uc))
        if p is None:
            return False, "Пакет не найден"
        if not p.active and p.price <= 0:
            return False, "Сначала задайте цену: /price <UC> <₽>"
        p.active = not p.active
        await s.commit()
        return True, "включён" if p.active else "выключен"


async def add_pack(uc: int, price: int, cost: int) -> bool:
    async with SessionLocal() as s:
        if await s.scalar(select(Product.id).where(Product.uc == uc)):
            return False
        last = await s.scalar(select(Product.sort).order_by(Product.sort.desc()).limit(1)) or 0
        s.add(Product(uc=uc, title=f"{uc} UC", price=price, cost=cost, active=price > 0, sort=last + 1))
        await s.commit()
        return True
