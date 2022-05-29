import asyncio
import logging.config

import fastapi.staticfiles
import fastapi.templating
import jira
import starlette

from . import api
from . import config
from . import crud
from . import database
from . import log
from . import schemas
from . import tasks


app = fastapi.FastAPI()
app.mount('/api', api.api)
app.mount('/static', fastapi.staticfiles.StaticFiles(directory='static'),
          name='static')

templates = fastapi.templating.Jinja2Templates(directory='templates')

database.Base.metadata.create_all(bind=database.engine)

logging.config.dictConfig(log.LogConfig().dict())
logger = logging.getLogger(__name__)


# Events
@app.on_event('startup')
async def startup() -> None:
    app.state.jira = jira.JIRA(config.JIRA_DOMAIN,
                               basic_auth=(config.JIRA_USERNAME,
                                           config.JIRA_TOKEN))
    # TODO: dynamic user selection
    app.state.myself = app.state.jira.myself()['displayName']
    logger.info('startup(): connected to jira as "%s"', app.state.myself)

    await database.database.connect()

    # TODO: attach error handler
    asyncio.create_task(tasks.fetch(app.state.jira))


@app.on_event('shutdown')
async def shutdown() -> None:
    await database.database.disconnect()


# Routes
@app.get('/issues', response_class=fastapi.responses.HTMLResponse)
async def list_issues(
        request: fastapi.Request,
) -> starlette.templating._TemplateResponse:
    issues = await crud.read_issues()
    meta = schemas.Meta(issues)
    return templates.TemplateResponse(
        'issues.list.html',
        {'request': request, 'config': config, 'issues': issues,
         'meta': meta})


@app.get('/mine', response_class=fastapi.responses.HTMLResponse)
async def list_my_issues(
        request: fastapi.Request,
) -> starlette.templating._TemplateResponse:
    issues = await crud.read_issues_for_user(request.app.state.myself)
    meta = schemas.Meta(issues)
    return templates.TemplateResponse(
        'issues.list.html',
        {'request': request, 'config': config, 'issues': issues,
         'meta': meta})


@app.get('/issues/{key}', response_class=fastapi.responses.HTMLResponse)
async def show_issue(request: fastapi.Request,
                     key: str) -> starlette.templating._TemplateResponse:
    issue = await crud.read_issue(key)
    if not issue:
        raise fastapi.HTTPException(status_code=404)

    return templates.TemplateResponse(
        'issues.show.html',
        {'request': request, 'config': config, 'issue': issue})


@app.get('/settings', response_class=fastapi.responses.HTMLResponse)
async def settings(
        request: fastapi.Request,
) -> starlette.templating._TemplateResponse:
    return templates.TemplateResponse(
        'settings.html',
        {'request': request, 'config': config,
         'myself': request.app.state.myself})


@app.get('/triage', response_class=fastapi.responses.HTMLResponse)
async def list_triagable_issues(
        request: fastapi.Request,
) -> starlette.templating._TemplateResponse:
    issues = await crud.read_issues_needing_triage()
    meta = schemas.Meta(issues)
    return templates.TemplateResponse(
        'issues.list.html',
        {'request': request, 'config': config, 'issues': issues,
         'meta': meta})
