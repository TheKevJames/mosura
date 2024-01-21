from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlalchemy.ext.asyncio import create_async_engine

from . import config


engine = create_async_engine(
    f'sqlite+aiosqlite:///{config.settings.mosura_appdata}/mosura.db',
    connect_args={'check_same_thread': False},
    # echo=True,
)
session = async_sessionmaker(engine)
