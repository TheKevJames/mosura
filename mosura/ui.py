import datetime

import fastapi.templating
import starlette

from . import config
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
) -> starlette.templating._TemplateResponse:
    return templates.TemplateResponse(
        'home.html',
        {'request': request, 'settings': config.settings})


@router.get('/gannt', response_class=fastapi.responses.HTMLResponse)
async def gannt(
        request: fastapi.Request,
        quarter: str | None = None,
) -> starlette.templating._TemplateResponse:
    okr_label = config.settings.jira_label_okr
    # TODO: include Closed
    issues = [issue for issue in await crud.read_issues()
              if okr_label in {x.label for x in issue.labels}]

    q = schemas.Quarter.from_display(quarter)
    schedule = schemas.Schedule(issues, quarter=q)

    issues = [x for x in issues
              if x not in schedule.raw
              and not q.uncontained(x)]

    return templates.TemplateResponse(
        'gannt.html',
        {'request': request, 'settings': config.settings, 'issues': issues,
         'okr_label': okr_label, 'schedule': schedule})


@router.get('/issues', response_class=fastapi.responses.HTMLResponse)
async def list_issues(
        request: fastapi.Request,
) -> starlette.templating._TemplateResponse:
    issues = await crud.read_issues()
    meta = schemas.Meta(issues)
    return templates.TemplateResponse(
        'issues.list.html',
        {'request': request, 'settings': config.settings, 'issues': issues,
         'meta': meta})


@router.get('/mine', response_class=fastapi.responses.HTMLResponse)
async def list_my_issues(
        request: fastapi.Request,
) -> starlette.templating._TemplateResponse:
    issues = await crud.read_issues_for_user(request.app.state.myself)
    meta = schemas.Meta(issues)
    return templates.TemplateResponse(
        'issues.list.html',
        {'request': request, 'settings': config.settings, 'issues': issues,
         'meta': meta})


@router.get('/issues/{key}', response_class=fastapi.responses.HTMLResponse)
async def show_issue(request: fastapi.Request,
                     key: str) -> starlette.templating._TemplateResponse:
    issue = await crud.read_issue(key)
    if not issue:
        raise fastapi.HTTPException(status_code=404)

    return templates.TemplateResponse(
        'issues.show.html',
        {'request': request, 'settings': config.settings, 'issue': issue})


@router.get('/settings', response_class=fastapi.responses.HTMLResponse)
async def settings(
        request: fastapi.Request,
) -> starlette.templating._TemplateResponse:
    return templates.TemplateResponse(
        'settings.html',
        {'request': request, 'settings': config.settings,
         'myself': request.app.state.myself})


@router.get('/triage', response_class=fastapi.responses.HTMLResponse)
async def list_triagable_issues(
        request: fastapi.Request,
) -> starlette.templating._TemplateResponse:
    issues = await crud.read_issues_needing_triage()
    meta = schemas.Meta(issues)
    return templates.TemplateResponse(
        'issues.list.html',
        {'request': request, 'settings': config.settings, 'issues': issues,
         'meta': meta})
