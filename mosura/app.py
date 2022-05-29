import asyncio
import logging.config
from typing import Any

import fastapi.staticfiles
import jira

from . import api
from . import config
from . import database
from . import log
from . import tasks
from . import ui


app = fastapi.FastAPI()
app.include_router(ui.router)
app.include_router(api.router, prefix='/api/v0')
app.include_router(api.router, prefix='/api/latest')
app.mount('/static', fastapi.staticfiles.StaticFiles(directory='static'),
          name='static')

database.Base.metadata.create_all(bind=database.engine)

logging.config.dictConfig(log.LogConfig().dict())
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
    app.state.jira = jira.JIRA(config.settings.jira_domain,
                               basic_auth=(config.settings.jira_username,
                                           config.settings.jira_token))
    # TODO: dynamic user selection
    app.state.myself = app.state.jira.myself()['displayName']
    logger.info('startup(): connected to jira as "%s"', app.state.myself)

    await database.database.connect()

    asyncio.get_event_loop().set_exception_handler(log_exception)
    asyncio.create_task(tasks.fetch_closed(app.state.jira))
    asyncio.create_task(tasks.fetch_open(app.state.jira))


@app.on_event('shutdown')
async def shutdown() -> None:
    await database.database.disconnect()
