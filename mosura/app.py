import asyncio
import logging.config

import fastapi.staticfiles

from . import api
from . import config
from . import tasks
from . import ui


app = fastapi.FastAPI()
app.include_router(ui.router)
app.include_router(api.router, prefix='/api/v0')
app.include_router(api.router, prefix='/api/latest')
app.mount('/static', fastapi.staticfiles.StaticFiles(directory='static'),
          name='static')

logger = logging.getLogger(__name__)


@app.exception_handler(fastapi.exceptions.RequestValidationError)
async def handle_validation_errors(
        _request: fastapi.Request,
        exc: fastapi.exceptions.RequestValidationError,
) -> fastapi.responses.JSONResponse:
    logger.error('could not parse payload', exc_info=exc)
    return fastapi.responses.JSONResponse(
        status_code=fastapi.status.HTTP_422_UNPROCESSABLE_ENTITY,
        content=exc.body,
    )


# Events
@app.on_event('startup')
async def startup() -> None:
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
