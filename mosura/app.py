import asyncio
import os

import fastapi
import jira


JIRA_DOMAIN = os.environ['JIRA_DOMAIN']
JIRA_PROJECT = os.environ['JIRA_PROJECT']
JIRA_TOKEN = os.environ['JIRA_TOKEN']
JIRA_USERNAME = os.environ['JIRA_USERNAME']

app = fastapi.FastAPI()


# Events
@app.on_event('startup')
async def startup_event() -> None:
    app.state.jira = jira.JIRA(JIRA_DOMAIN,
                               basic_auth=(JIRA_USERNAME, JIRA_TOKEN))
    app.state.issues = {}

    asyncio.create_task(fetch())


# Tasks
async def fetch() -> None:
    while True:
        jql = f"project = '{JIRA_PROJECT}' AND status != 'Closed'"
        fields = ('key,summary,description,status,assignee,priority,'
                  'components,labels')
        issues = app.state.jira.search_issues(jql, maxResults=0, fields=fields,
                                              expand='renderedFields')
        for issue in issues:
            app.state.issues[issue.key] = issue

        await asyncio.sleep(300)


# Routes
@app.get('/')
async def root() -> dict[str, dict[str, str]]:
    return {'issues': {k: v.fields.summary
                       for k, v in app.state.issues.items()}}


@app.get('/{key}')
async def fetch_issue(key: str) -> dict[str, str]:
    try:
        issue = app.state.issues[key]
    except KeyError as e:
        raise fastapi.HTTPException(status_code=404,
                                    detail='key not found') from e
    else:
        return {'issue': issue.fields.summary}
