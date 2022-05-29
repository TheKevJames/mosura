import asyncio
import datetime
import logging.config
import random

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
    app.state.myself = app.state.jira.myself()['displayName']
    logger.info('startup(): connected to jira as "%s"', app.state.myself)

    await database.database.connect()
    asyncio.create_task(fetch())


@app.on_event('shutdown')
async def shutdown() -> None:
    await database.database.disconnect()


# Tasks
async def fetch() -> None:
    while True:
        now = datetime.datetime.now(datetime.timezone.utc)
        latest = await crud.read_task('fetch')
        if latest and latest + datetime.timedelta(minutes=5) > now:
            logger.debug('fetch(): too soon, sleeping')
            await asyncio.sleep(random.uniform(0, 60))
            continue

        logger.info('fetch(): fetching data')
        jql = f"project = '{config.JIRA_PROJECT}'"
        fields = ('key,summary,description,status,assignee,priority,'
                  'components,labels')
        issues = await asyncio.to_thread(app.state.jira.search_issues, jql,
                                         maxResults=0, fields=fields,
                                         expand='renderedFields')
        for issue in issues:
            for component in issue.fields.components:
                await crud.create_issue_component(
                    schemas.ComponentCreate(component=str(component)),
                    issue.key)
            for label in issue.fields.labels:
                await crud.create_issue_label(
                    schemas.LabelCreate(label=label), issue.key)

            await crud.create_issue(schemas.IssueCreate(
                assignee=str(issue.fields.assignee),
                description=issue.fields.description,
                key=issue.key,
                priority=str(issue.fields.priority),
                status=str(issue.fields.status),
                summary=issue.fields.summary,
            ))

        logger.info('fetch(): fetched %d issues', len(issues))
        now = datetime.datetime.now(datetime.timezone.utc)
        await crud.update_task('fetch', now)


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
