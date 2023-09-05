import asyncio
import logging.config
from typing import Any

import fastapi.staticfiles

from . import api
from . import config
from . import database
from . import tasks
from . import ui


app = fastapi.FastAPI()
app.include_router(ui.router)
app.include_router(api.router, prefix='/api/v0')
app.include_router(api.router, prefix='/api/latest')
app.mount('/static', fastapi.staticfiles.StaticFiles(directory='static'),
          name='static')

database.Base.metadata.create_all(bind=database.engine)

logger = logging.getLogger(__name__)


def log_exception(_loop: asyncio.AbstractEventLoop,
                  context: dict[str, Any]) -> None:
    if context.get('exception'):
        logger.error(context['message'], exc_info=context['exception'])
        return

    logger.error(context['message'])


# Events
@app.on_event('startup')
async def startup() -> None:
    await database.database.connect()

    app.state.tasks = await tasks.spawn(config.settings.jira_project)
    logger.info('startup(): begun polling tasks')


@app.on_event('shutdown')
async def shutdown() -> None:
    logger.info('shutdown(): stopping polling tasks')
    for task in app.state.tasks:
        task.cancel()

    try:
        await asyncio.gather(*app.state.tasks)
    except asyncio.CancelledError:
        pass

    await database.database.disconnect()
