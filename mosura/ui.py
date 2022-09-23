import datetime

import fastapi.templating
import starlette

from . import crud
from . import schemas


router = fastapi.APIRouter(tags=['ui'])

templates = fastapi.templating.Jinja2Templates(directory='templates')


def dateformat(x: datetime.datetime | None) -> str:
    if x is None:
        return ''
    return x.strftime('%Y-%m-%d')


templates.env.filters['dateformat'] = dateformat


@router.get('/', response_class=fastapi.responses.HTMLResponse)
async def home(
        request: fastapi.Request,
) -> starlette.responses.Response:
    return templates.TemplateResponse(
        'home.html',
        {'request': request})


@router.get('/gannt', response_class=fastapi.responses.HTMLResponse)
async def gannt(
        request: fastapi.Request,
        quarter: str | None = None,
        jira_label_okr: str = fastapi.Cookie(default='okr'),
) -> starlette.responses.Response:
    # TODO: include Closed
    issues = [issue for issue in await crud.read_issues()
              if jira_label_okr in {x.label for x in issue.labels}]

    q = schemas.Quarter.from_display(quarter)
    schedule = schemas.Schedule(issues, quarter=q)

    issues = [x for x in issues
              if x not in schedule.raw
              and not q.uncontained(x)]

    return templates.TemplateResponse(
        'gannt.html',
        {'request': request, 'issues': issues, 'okr_label': jira_label_okr,
         'schedule': schedule})


@router.get('/issues', response_class=fastapi.responses.HTMLResponse)
async def list_issues(
        request: fastapi.Request,
) -> starlette.responses.Response:
    issues = await crud.read_issues()
    meta = schemas.Meta(issues)
    return templates.TemplateResponse(
        'issues.list.html',
        {'request': request, 'issues': issues, 'meta': meta})


@router.get('/mine', response_class=fastapi.responses.HTMLResponse)
async def list_my_issues(
        request: fastapi.Request,
        jira_domain: str | None = fastapi.Cookie(default=None),
        jira_label_okr: str = fastapi.Cookie(default='okr'),
        jira_project: str | None = fastapi.Cookie(default=None),
        jira_token: str | None = fastapi.Cookie(default=None),
        jira_username: str | None = fastapi.Cookie(default=None),
) -> starlette.responses.Response:
    settings = schemas.Settings(
        jira_domain=jira_domain, jira_label_okr=jira_label_okr,
        jira_project=jira_project, jira_token=jira_token,
        jira_username=jira_username)

    client = settings.jira_client
    if not client:
        return fastapi.responses.RedirectResponse('/settings')

    myself = client.myself()['displayName']
    issues = await crud.read_issues_for_user(myself)
    meta = schemas.Meta(issues)
    return templates.TemplateResponse(
        'issues.list.html',
        {'request': request, 'issues': issues, 'meta': meta})


@router.get('/issues/{key}', response_class=fastapi.responses.HTMLResponse)
async def show_issue(
        request: fastapi.Request,
        key: str,
        jira_domain: str = fastapi.Cookie(),
) -> starlette.responses.Response:
    issue = await crud.read_issue(key)
    if not issue:
        raise fastapi.HTTPException(status_code=404)

    return templates.TemplateResponse(
        'issues.show.html',
        {'request': request, 'jira_domain': jira_domain, 'issue': issue})


@router.get('/settings', response_class=fastapi.responses.HTMLResponse)
async def show_settings(
        request: fastapi.Request,
        jira_domain: str | None = fastapi.Cookie(default=None),
        jira_label_okr: str = fastapi.Cookie(default='okr'),
        jira_project: str | None = fastapi.Cookie(default=None),
        jira_token: str | None = fastapi.Cookie(default=None),
        jira_username: str | None = fastapi.Cookie(default=None),
) -> starlette.responses.Response:
    settings = schemas.Settings(
        jira_domain=jira_domain, jira_label_okr=jira_label_okr,
        jira_project=jira_project, jira_token=jira_token,
        jira_username=jira_username)

    client = settings.jira_client
    myself = 'Please configure your Jira credentials'
    if client:
        myself = client.myself()['displayName']

    return templates.TemplateResponse(
        'settings.html',
        {'request': request, 'settings': settings, 'myself': myself})


@router.get('/triage', response_class=fastapi.responses.HTMLResponse)
async def list_triagable_issues(
        request: fastapi.Request,
) -> starlette.responses.Response:
    issues = await crud.read_issues_needing_triage()
    meta = schemas.Meta(issues)
    return templates.TemplateResponse(
        'issues.list.html',
        {'request': request, 'issues': issues, 'meta': meta})
