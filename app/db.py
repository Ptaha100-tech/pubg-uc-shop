from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from .config import get_settings

engine = create_async_engine(get_settings().database_url, pool_pre_ping=True)
SessionLocal: async_sessionmaker[AsyncSession] = async_sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def _add_missing_columns(sync_conn) -> None:
    """Мини-миграция: create_all не добавляет колонки в уже существующие таблицы,
    поэтому новые поля добавляем вручную. Данные при этом не затрагиваются."""
    columns = {c["name"] for c in inspect(sync_conn).get_columns("products")}
    if "old_price" not in columns:
        sync_conn.execute(text("ALTER TABLE products ADD COLUMN old_price INTEGER NOT NULL DEFAULT 0"))


async def init_db() -> None:
    from . import models  # noqa: F401  (регистрирует таблицы)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_add_missing_columns)
