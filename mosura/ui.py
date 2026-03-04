import datetime
from typing import Any

import fastapi.templating
import starlette

from . import database
from . import models
from . import schemas


router = fastapi.APIRouter(tags=['ui'])

templates = fastapi.templating.Jinja2Templates(directory='templates')


def dateformat(x: datetime.datetime | None) -> str:
    if x is None:
        return 'None'
    return x.strftime('%Y-%m-%d')


def dayformat(x: datetime.datetime | None) -> str:
    if x is None:
        return ''
    return x.strftime('%b %-d')


def timeformat(x: datetime.timedelta) -> str:
    if x.days > 0:
        return f'{x.days} Days'
    if x.seconds > 3600:
        return f'{-(-x.seconds // 3600)} Hours'
    if x.total_seconds() == 0:
        return 'Unset'
    return '<1 Hour'


# TODO: issue color template?
templates.env.filters['dateformat'] = dateformat
templates.env.filters['dayformat'] = dayformat
templates.env.filters['timeformat'] = timeformat


async def _build_timeline(
        request: fastapi.Request,
        session: Any,
        selected_date: datetime.date,
        current_date: datetime.date,
        weeks_before: int,
        weeks_after: int,
) -> schemas.Timeline:
    transitions_by_issue: dict[str, list[schemas.IssueTransition]] = {}

    # TODO: for perf, move some filters out of Timeline.from_issues() and into
    # this SQL command.
    issues = await models.Issue.get(
        assignee=request.app.state.tracked_user_name,
        closed=True,
        session=session,
    )

    issue_keys = [issue.key for issue in issues]
    if issue_keys:
        transitions = await models.IssueTransition.get_by_keys(
            issue_keys,
            session=session,
        )
        for transition in transitions:
            transitions_by_issue.setdefault(
                transition.key,
                [],
            ).append(transition)

    timeline = schemas.Timeline.from_issues(
        issues,
        selected_date=selected_date,
        current_date=current_date,
        transitions=transitions_by_issue,
        weeks_before=weeks_before,
        weeks_after=weeks_after,
    )
    _enrich_timeline_for_template(timeline, current_date=current_date)
    return timeline


@router.get('/', response_class=fastapi.responses.HTMLResponse)
async def home(
        request: fastapi.Request,
) -> starlette.responses.Response:
    current_date = datetime.datetime.now(datetime.UTC).date()

    async with database.session_from_app(request.app) as session:
        my_issues = await models.Issue.get(
            assignee=request.app.state.tracked_user_name,
            closed=False,
            session=session,
        )
        timeline = await _build_timeline(
            request,
            session,
            current_date,
            current_date,
            weeks_before=1,
            weeks_after=1,
        )

    my_issues.sort(key=lambda i: i.priority.sort_value, reverse=True)

    context = {'my_issues': my_issues[:5], 'timeline': timeline}
    return templates.TemplateResponse(request, 'home.html', context)


@router.get('/issues', response_class=fastapi.responses.HTMLResponse)
async def list_issues(
        request: fastapi.Request,
) -> starlette.responses.Response:
    async with database.session_from_app(request.app) as session:
        issues = await models.Issue.get(closed=False, session=session)

    meta = schemas.Meta.from_issues(issues)
    context = {'issues': issues, 'meta': meta, 'title': 'Issues'}
    return templates.TemplateResponse(request, 'issues.list.html', context)


@router.get('/mine', response_class=fastapi.responses.HTMLResponse)
async def list_my_issues(
        request: fastapi.Request,
) -> starlette.responses.Response:
    tracked_user_name = request.app.state.tracked_user_name

    async with database.session_from_app(request.app) as session:
        issues = await models.Issue.get(
            assignee=tracked_user_name, closed=False,
            session=session,
        )

    meta = schemas.Meta.from_issues(issues)
    context = {'issues': issues, 'meta': meta, 'title': 'My Issues'}
    return templates.TemplateResponse(request, 'issues.list.html', context)


@router.get('/issues/{key}', response_class=fastapi.responses.HTMLResponse)
async def show_issue(
        request: fastapi.Request,
        key: str,
) -> starlette.responses.Response:
    async with database.session_from_app(request.app) as session:
        issues = await models.Issue.get(key=key, closed=True, session=session)

    if not issues:
        raise fastapi.HTTPException(status_code=404)

    context = {
        'settings': request.app.state.settings, 'issue': issues[0],
        'Priority': schemas.Priority,
    }
    return templates.TemplateResponse(request, 'issues.show.html', context)


@router.get('/settings', response_class=fastapi.responses.HTMLResponse)
async def show_settings(
        request: fastapi.Request,
) -> starlette.responses.Response:
    async with database.session_from_app(request.app) as session:
        custom_jql = await models.Setting.get('custom_jql', session=session)
    context = {
        'settings': request.app.state.settings,
        'custom_jql': custom_jql,
    }
    return templates.TemplateResponse(request, 'settings.html', context)


def _enrich_timeline_for_template(
        timeline: schemas.Timeline,
        current_date: datetime.date,
) -> None:
    """Add computed percentages and CSS classes to timeline issues."""
    total_days = len(timeline.boxes) * 7
    view_start = timeline.boxes[0][0]

    for issue in timeline.issues:
        issue.calculate_rendering(total_days, view_start, current_date)

        previous = None
        for segment in issue.segments:
            if segment.left_percent:
                previous = segment
                continue

            segment.calculate_rendering(previous, total_days, view_start)
            previous = segment


@router.get('/timeline', response_class=fastapi.responses.HTMLResponse)
async def show_timeline(
        request: fastapi.Request,
        date: str | None = None,
) -> starlette.responses.Response:
    current_date = datetime.datetime.now(datetime.UTC).date()
    selected_date = (
        datetime.date.fromisoformat(date) if date
        else current_date
    )

    async with database.session_from_app(request.app) as session:
        timeline = await _build_timeline(
            request,
            session,
            selected_date,
            current_date,
            weeks_before=3,
            weeks_after=5,
        )

    context = {'timeline': timeline}
    return templates.TemplateResponse(request, 'timeline.html', context)


@router.get('/triage', response_class=fastapi.responses.HTMLResponse)
async def list_triagable_issues(
        request: fastapi.Request,
) -> starlette.responses.Response:
    async with database.session_from_app(request.app) as session:
        issues = await models.Issue.get(needs_triage=True, session=session)

    meta = schemas.Meta.from_issues(issues)
    context = {'issues': issues, 'meta': meta, 'title': 'Triage'}
    return templates.TemplateResponse(request, 'issues.list.html', context)
