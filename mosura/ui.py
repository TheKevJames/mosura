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
    return templates.TemplateResponse(request, 'home.html')


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

    context = {'issues': issues, 'schedule': schedule,
               'settings': config.settings}
    return templates.TemplateResponse(request, 'gannt.html', context)


@router.get('/issues', response_class=fastapi.responses.HTMLResponse)
async def list_issues(
        request: fastapi.Request,
) -> starlette.responses.Response:
    async with database.session() as session:
        issues = await models.Issue.get(closed=False, session=session)

    meta = schemas.Meta.from_issues(issues)
    context = {'issues': issues, 'meta': meta}
    return templates.TemplateResponse(request, 'issues.list.html', context)


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
    context = {'issues': issues, 'meta': meta}
    return templates.TemplateResponse(request, 'issues.list.html', context)


@router.get('/issues/{key}', response_class=fastapi.responses.HTMLResponse)
async def show_issue(
        request: fastapi.Request,
        key: str,
) -> starlette.responses.Response:
    async with database.session() as session:
        issues = await models.Issue.get(key=key, closed=True, session=session)

    if not issues:
        raise fastapi.HTTPException(status_code=404)

    context = {'settings': config.settings, 'issue': issues[0],
               'Priority': schemas.Priority}
    return templates.TemplateResponse(request, 'issues.show.html', context)


@router.get('/settings', response_class=fastapi.responses.HTMLResponse)
async def show_settings(
        request: fastapi.Request,
        commons: config.CommonsDep,
) -> starlette.responses.Response:
    context = {'settings': config.settings, 'commons': commons}
    return templates.TemplateResponse(request, 'settings.html', context)


@router.get('/triage', response_class=fastapi.responses.HTMLResponse)
async def list_triagable_issues(
        request: fastapi.Request,
) -> starlette.responses.Response:
    async with database.session() as session:
        issues = await models.Issue.get(needs_triage=True, session=session)

    meta = schemas.Meta.from_issues(issues)
    context = {'issues': issues, 'meta': meta}
    return templates.TemplateResponse(request, 'issues.list.html', context)
