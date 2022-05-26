import os

import fastapi
import jira


app = fastapi.FastAPI()


@app.on_event('startup')
async def startup_event() -> None:
    app.state.jira = jira.JIRA(os.environ['JIRA_DOMAIN'],
                               basic_auth=(os.environ['JIRA_USERNAME'],
                                           os.environ['JIRA_TOKEN']))


@app.get('/')
async def root() -> dict[str, str]:
    return {'message': 'Hello World!'}


@app.get('/{issue_id}')
async def fetch(issue_id: str) -> dict[str, str]:
    try:
        x = app.state.jira.issue(issue_id)
        return {'issue': f'{x}'}
    except jira.exceptions.JIRAError as e:
        raise fastapi.HTTPException(status_code=e.status_code, detail=e.text)
