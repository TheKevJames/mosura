import asyncio
import contextlib
import logging.config
from collections.abc import AsyncIterator

import fastapi.staticfiles

from . import api
from . import config
from . import database
from . import models
from . import tasks
from . import ui


logger = logging.getLogger(__name__)


@contextlib.asynccontextmanager
async def lifespan(_app: fastapi.FastAPI) -> AsyncIterator[None]:
    async with database.engine.begin() as conn:
        await conn.run_sync(models.Base.metadata.create_all)
    logger.info('startup(): initialized db')

    _app.state.tasks = await tasks.spawn(config.settings.jira_project)
    logger.info('startup(): begun polling tasks')

    yield

    logger.info('shutdown(): stopping polling tasks')
    for task in _app.state.tasks:
        task.cancel()

    try:
        await asyncio.gather(*_app.state.tasks)
    except asyncio.CancelledError:
        pass


app = fastapi.FastAPI(lifespan=lifespan)
app.include_router(ui.router)
app.include_router(api.router, prefix='/api/v0')
app.include_router(api.router, prefix='/api/latest')
app.mount('/static', fastapi.staticfiles.StaticFiles(directory='static'),
          name='static')


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
