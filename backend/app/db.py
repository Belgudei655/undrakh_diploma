from collections.abc import AsyncGenerator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import get_settings

settings = get_settings()
engine = create_async_engine(settings.database_url, future=True)
SessionLocal = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with SessionLocal() as session:
        yield session


async def _ensure_device_columns(connection) -> None:
    result = await connection.execute(text("PRAGMA table_info(devices)"))
    existing_columns = {row[1] for row in result.fetchall()}

    column_definitions = {
        "last_water_value": "INTEGER",
        "water_detected": "BOOLEAN NOT NULL DEFAULT 0",
        "relay_open": "BOOLEAN NOT NULL DEFAULT 0",
        "desired_relay_open": "BOOLEAN NOT NULL DEFAULT 0",
        "auto_close_on_water_detect": "BOOLEAN NOT NULL DEFAULT 1",
    }

    for column_name, sql_definition in column_definitions.items():
        if column_name in existing_columns:
            continue
        await connection.execute(text(f"ALTER TABLE devices ADD COLUMN {column_name} {sql_definition}"))


async def init_db() -> None:
    from app.models import Command, Device

    _ = (Device, Command)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
        await _ensure_device_columns(connection)
