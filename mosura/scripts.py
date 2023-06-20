import uvicorn

from . import config


def devserver() -> None:
    uvicorn.run('mosura.app:app', port=config.settings.mosura_port,
                reload=True)
