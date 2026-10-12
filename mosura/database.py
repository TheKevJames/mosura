import contextlib
from collections.abc import AsyncGenerator

import fastapi
import sqlalchemy.ext.asyncio

from . import config


def build_engine(
    settings: config.Settings,
) -> sqlalchemy.ext.asyncio.AsyncEngine:
    return sqlalchemy.ext.asyncio.create_async_engine(
        f'sqlite+aiosqlite:///{settings.mosura_appdata}/mosura.db',
        connect_args={'check_same_thread': False},
    )


def build_sessionmaker(
    engine: sqlalchemy.ext.asyncio.AsyncEngine,
) -> sqlalchemy.ext.asyncio.async_sessionmaker[
    sqlalchemy.ext.asyncio.AsyncSession
]:
    return sqlalchemy.ext.asyncio.async_sessionmaker(engine)


@contextlib.asynccontextmanager
async def session_from_app(
    app: fastapi.FastAPI,
) -> AsyncGenerator[sqlalchemy.ext.asyncio.AsyncSession, None]:
    async with app.state.sessionmaker() as session:
        yield session
