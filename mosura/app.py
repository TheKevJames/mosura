import asyncio
import datetime
import logging.config
import os
import random

import fastapi.staticfiles
import fastapi.templating
import jira
import starlette

from . import api
from . import crud
from . import database
from . import log
from . import schemas


JIRA_DOMAIN = os.environ['JIRA_DOMAIN']
JIRA_PROJECT = os.environ['JIRA_PROJECT']
JIRA_TOKEN = os.environ['JIRA_TOKEN']
JIRA_USERNAME = os.environ['JIRA_USERNAME']

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
    app.state.jira = jira.JIRA(JIRA_DOMAIN,
                               basic_auth=(JIRA_USERNAME, JIRA_TOKEN))

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

        await crud.update_task('fetch', now)

        logger.info('fetch(): fetching data')
        jql = f"project = '{JIRA_PROJECT}' AND status != 'Closed'"
        fields = ('key,summary,description,status,assignee,priority,'
                  'components,labels')
        issues = app.state.jira.search_issues(jql, maxResults=0, fields=fields,
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


# Routes
@app.get('/issues', response_class=fastapi.responses.HTMLResponse)
async def list_issues(
        request: fastapi.Request,
) -> starlette.templating._TemplateResponse:
    issues = await crud.read_issues(limit=500)
    return templates.TemplateResponse(
        'issues.list.html',
        {'request': request, 'issues': issues, 'jira_domain': JIRA_DOMAIN})


@app.get('/issues/{key}', response_class=fastapi.responses.HTMLResponse)
async def show_issue(request: fastapi.Request,
                     key: str) -> starlette.templating._TemplateResponse:
    issue = await crud.read_issue(key)
    if not issue:
        raise fastapi.HTTPException(status_code=404)

    return templates.TemplateResponse(
        'issues.show.html',
        {'request': request, 'issue': issue, 'jira_domain': JIRA_DOMAIN})
