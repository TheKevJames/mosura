import contextlib
from collections.abc import AsyncIterator

import fastapi
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.ext.asyncio import create_async_engine

from .config import Settings


def build_engine(settings: Settings) -> AsyncEngine:
    return create_async_engine(
        f'sqlite+aiosqlite:///{settings.mosura_appdata}/mosura.db',
        connect_args={'check_same_thread': False},
    )


def build_sessionmaker(
        engine: AsyncEngine,
) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine)


@contextlib.asynccontextmanager
async def session_from_app(
        app: fastapi.FastAPI,
) -> AsyncIterator[AsyncSession]:
    async with app.state.sessionmaker() as session:
        yield session
