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


def _log_task_exception(task: asyncio.Task[None]) -> None:
    with contextlib.suppress(asyncio.CancelledError):
        exc = task.exception()
        if exc is not None:
            name = task.get_name()
            logger.error('background task crashed: %s', name, exc_info=exc)


def load_users() -> list[str]:
    if not config.settings.jira_team:
        return []

    # https://github.com/pycontribs/jira/issues/1761
    project = config.settings.jira_project
    team = config.settings.jira_team
    base = (
        f'{{server}}/gateway/api/public/teams/v1/org/{project}/teams/{team}'
        '/{path}'
    )
    resp = config.jira_client._get_json(  # pylint: disable=protected-access
        'members', {'first': 40}, base, use_post=True,
    )
    return [x['accountId'] for x in resp.get('results', [])]


@contextlib.asynccontextmanager
async def lifespan(app_: fastapi.FastAPI) -> AsyncIterator[None]:
    async with database.engine.begin() as conn:
        await conn.run_sync(models.Base.metadata.create_all)
    logger.info('startup(): initialized db')

    users = load_users()
    logger.info('startup(): loaded %d users', len(users))

    # TODO: catch errors in these tasks immediately and crash/retry
    app_.state.tasks = await tasks.spawn(users)
    for t in app_.state.tasks:
        t.add_done_callback(_log_task_exception)
        if t.done():
            _log_task_exception(t)

    logger.info('startup(): begun polling tasks')

    yield

    logger.info('shutdown(): stopping polling tasks')
    for task in app_.state.tasks:
        task.cancel()

    await asyncio.gather(*app_.state.tasks, return_exceptions=True)


app = fastapi.FastAPI(lifespan=lifespan)
app.include_router(ui.router)
app.include_router(api.router, prefix='/api/v0')
app.include_router(api.router, prefix='/api/latest')
app.mount(
    '/static', fastapi.staticfiles.StaticFiles(directory='static'),
    name='static',
)


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
