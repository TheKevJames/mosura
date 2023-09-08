import datetime

import fastapi.templating
import starlette

from . import config
from . import database
from . import models
from . import schemas


router = fastapi.APIRouter(tags=['ui'])

templates = fastapi.templating.Jinja2Templates(directory='templates')


def dateformat(x: datetime.datetime | None) -> str:
    if x is None:
        return ''
    return x.strftime('%Y-%m-%d')


def timeformat(x: datetime.timedelta) -> str:
    if x.days > 0:
        return f'{x.days} Days'
    if x.seconds > 3600:
        return f'{-(-x.seconds // 3600)} Hours'
    if x.total_seconds() == 0:
        return 'Unset'
    return '<1 Hour'


templates.env.filters['dateformat'] = dateformat
templates.env.filters['timeformat'] = timeformat


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
) -> starlette.responses.Response:
    async with database.session() as session:
        okr_label = config.settings.jira_label_okr
        issues = [
            iss for iss in await models.Issue.get(closed=True, session=session)
            if okr_label in {x.label for x in iss.labels}
        ]

    q = schemas.Quarter.from_display(quarter)
    schedule = schemas.Schedule.init(issues, quarter=q)

    issues = [x for x in issues
              if x not in schedule.raw
              and not q.uncontained(x)]

    return templates.TemplateResponse(
        'gannt.html',
        {'request': request, 'issues': issues, 'schedule': schedule,
         'settings': config.settings})


@router.get('/issues', response_class=fastapi.responses.HTMLResponse)
async def list_issues(
        request: fastapi.Request,
) -> starlette.responses.Response:
    async with database.session() as session:
        issues = await models.Issue.get(closed=False, session=session)

    meta = schemas.Meta.from_issues(issues)
    return templates.TemplateResponse(
        'issues.list.html',
        {'request': request, 'issues': issues, 'meta': meta})


@router.get('/mine', response_class=fastapi.responses.HTMLResponse)
async def list_my_issues(
        request: fastapi.Request,
        commons: config.CommonsDep,
) -> starlette.responses.Response:
    if not commons.user:
        raise fastapi.HTTPException(status_code=403)

    async with database.session() as session:
        issues = await models.Issue.get(assignee=commons.user, closed=False,
                                        session=session)

    meta = schemas.Meta.from_issues(issues)
    return templates.TemplateResponse(
        'issues.list.html',
        {'request': request, 'issues': issues, 'meta': meta})


@router.get('/issues/{key}', response_class=fastapi.responses.HTMLResponse)
async def show_issue(
        request: fastapi.Request,
        key: str,
) -> starlette.responses.Response:
    async with database.session() as session:
        issues = await models.Issue.get(key=key, closed=True, session=session)

    if not issues:
        raise fastapi.HTTPException(status_code=404)

    return templates.TemplateResponse(
        'issues.show.html',
        {'request': request, 'settings': config.settings, 'issue': issues[0],
         'Priority': schemas.Priority})


@router.get('/settings', response_class=fastapi.responses.HTMLResponse)
async def show_settings(
        request: fastapi.Request,
        commons: config.CommonsDep,
) -> starlette.responses.Response:
    return templates.TemplateResponse(
        'settings.html',
        {'request': request, 'settings': config.settings, 'commons': commons})


@router.get('/triage', response_class=fastapi.responses.HTMLResponse)
async def list_triagable_issues(
        request: fastapi.Request,
) -> starlette.responses.Response:
    async with database.session() as session:
        issues = await models.Issue.get(needs_triage=True, session=session)

    meta = schemas.Meta.from_issues(issues)
    return templates.TemplateResponse(
        'issues.list.html',
        {'request': request, 'issues': issues, 'meta': meta})
