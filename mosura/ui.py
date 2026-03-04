import datetime

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


@router.get('/', response_class=fastapi.responses.HTMLResponse)
async def home(
        request: fastapi.Request,
) -> starlette.responses.Response:
    transitions_by_issue: dict[str, list[schemas.IssueTransition]] = {}

    async with database.session_from_app(request.app) as session:
        my_issues = await models.Issue.get(
            assignee=request.app.state.tracked_user_name,
            closed=False,
            session=session,
        )
        timeline_issues = await models.Issue.get(
            assignee=request.app.state.tracked_user_name,
            closed=True,
            session=session,
        )

        issue_keys = [issue.key for issue in timeline_issues]
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

    my_issues.sort(key=lambda i: i.priority.sort_value, reverse=True)
    my_issues = my_issues[:5]

    current_date = datetime.datetime.now(datetime.UTC).date()
    timeline = schemas.Timeline.from_issues(
        timeline_issues,
        selected_date=current_date,
        current_date=current_date,
        transitions=transitions_by_issue,
        weeks_before=1,
        weeks_after=1,
    )
    _enrich_timeline_for_template(timeline, current_date=current_date)

    context = {'my_issues': my_issues, 'timeline': timeline}
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


def _mapped_status(status: str | None) -> str:
    if not status:
        return ''
    return schemas.IssueCreate.parse_status(status)


def _status_color_group(status: str | None) -> str:
    mapped = _mapped_status(status)
    if mapped in {'In Progress', 'Code Review', 'Ready for Testing'}:
        return 'in-progress'
    return mapped.lower().replace(' ', '-')


def _enrich_timeline_for_template(
        timeline: schemas.Timeline,
        current_date: datetime.date,
) -> None:
    """Add computed percentages and CSS classes to timeline issues."""
    # pylint: disable=too-many-locals
    total_days = len(timeline.boxes) * 7
    view_start = timeline.boxes[0][0]
    today = current_date

    for issue in getattr(timeline, 'issues', []):
        if hasattr(issue, 'status_css_class'):
            continue

        if hasattr(issue, 'startdate') and issue.startdate:
            days_from_start = (issue.startdate - view_start).days
            issue.startdate_percent = days_from_start / total_days * 100

        if (
            hasattr(issue, 'estimated_completion')
            and issue.estimated_completion
        ):
            days_from_start = (
                issue.estimated_completion - view_start
            ).days
            issue.estimated_completion_percent = (
                days_from_start / total_days * 100
            )

        if (
            hasattr(issue, 'overdue') and issue.overdue
            and hasattr(issue, 'estimated_completion')
            and issue.estimated_completion
        ):
            days_overdue = (today - issue.estimated_completion).days
            issue.overdue_width_percent = (
                days_overdue / total_days * 100
            )
        else:
            issue.overdue_width_percent = 0

        if (
            hasattr(issue, 'overdue_start') and issue.overdue_start
            and hasattr(issue, 'startdate') and issue.startdate
        ):
            days_not_started = (today - issue.startdate).days
            issue.overdue_start_width_percent = (
                days_not_started / total_days * 100
            )
        else:
            issue.overdue_start_width_percent = 0

        previous_segment = None
        previous_color_group = ''
        for segment in getattr(issue, 'segments', []):
            if hasattr(segment, 'left_percent'):
                previous_segment = segment
                previous_color_group = _status_color_group(segment.status)
                continue

            segment_start_offset = (segment.start - view_start).days
            # Render segment end date inclusively so a segment ending on a
            # given date still fills that date on the chart.
            segment_width = (segment.end - segment.start).days + 1
            segment.left_percent = segment_start_offset / total_days * 100
            segment.width_percent = max(
                segment_width / total_days * 100,
                0.1,
            )

            mapped_status = _mapped_status(segment.status)
            status_slug = mapped_status.lower().replace(' ', '-')
            segment.status_css_class = f'status-{status_slug}'
            segment.status_display = segment.status

            color_group = _status_color_group(segment.status)
            segment.show_transition_marker = bool(
                previous_segment
                and segment.left_percent > 0
                and color_group == previous_color_group,
            )

            previous_segment = segment
            previous_color_group = color_group


@router.get('/timeline', response_class=fastapi.responses.HTMLResponse)
async def show_timeline(
        request: fastapi.Request,
        date: str | None = None,
) -> starlette.responses.Response:
    transitions_by_issue: dict[str, list[schemas.IssueTransition]] = {}

    async with database.session_from_app(request.app) as session:
        # TODO: for perf, move some filters out of Timeline.from_issues()
        # and into this SQL command.
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

    current_date = datetime.datetime.now(datetime.UTC).date()
    selected_date = (
        datetime.date.fromisoformat(date) if date
        else current_date
    )

    timeline = schemas.Timeline.from_issues(
        issues,
        selected_date=selected_date,
        current_date=current_date,
        transitions=transitions_by_issue,
    )

    # Enrich timeline with computed positioning for template
    _enrich_timeline_for_template(timeline, current_date=current_date)

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
