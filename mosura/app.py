import asyncio
import os

import fastapi
import jira

from . import api
from . import crud
from . import database
from . import schemas


JIRA_DOMAIN = os.environ['JIRA_DOMAIN']
JIRA_PROJECT = os.environ['JIRA_PROJECT']
JIRA_TOKEN = os.environ['JIRA_TOKEN']
JIRA_USERNAME = os.environ['JIRA_USERNAME']

app = fastapi.FastAPI()
app.mount('/api', api.api)

database.Base.metadata.create_all(bind=database.engine)


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

        await asyncio.sleep(300)
