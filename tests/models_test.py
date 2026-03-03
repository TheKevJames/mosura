import datetime
from collections.abc import Awaitable
from collections.abc import Callable

import sqlalchemy.ext.asyncio

from mosura import models
from mosura import schemas


async def test_convert_field_response_dedupes_and_sorts(
    db_session: sqlalchemy.ext.asyncio.AsyncSession,
    issue_create_factory: Callable[..., schemas.IssueCreate],
    seed_issue: Callable[..., Awaitable[None]],
    issue_rows_fetcher: Callable[..., Awaitable[list[models.IssueRow]]],
) -> None:
    await seed_issue(
        issue_create_factory('MOS-1', status='In Progress', assignee='Ada'),
        components=['Platform', 'API'],
        labels=['feature', 'maintenance'],
    )
    await db_session.commit()

    rows = await issue_rows_fetcher(key='MOS-1')

    converted = models.convert_field_response(
        'MOS-1',
        rows,
        idx=9,
        name='component',
    )

    assert converted == [
        {'key': 'MOS-1', 'component': 'API'},
        {'key': 'MOS-1', 'component': 'Platform'},
    ]


async def test_convert_component_and_label_helpers(
    db_session: sqlalchemy.ext.asyncio.AsyncSession,
    issue_create_factory: Callable[..., schemas.IssueCreate],
    seed_issue: Callable[..., Awaitable[None]],
    issue_rows_fetcher: Callable[..., Awaitable[list[models.IssueRow]]],
) -> None:
    await seed_issue(
        issue_create_factory('MOS-1', status='In Progress', assignee='Ada'),
        components=['Platform', 'API'],
        labels=['bug', 'okr'],
    )
    await db_session.commit()

    rows = await issue_rows_fetcher(key='MOS-1')

    assert models.convert_component_response('MOS-1', rows) == [
        {'key': 'MOS-1', 'component': 'API'},
        {'key': 'MOS-1', 'component': 'Platform'},
    ]
    assert models.convert_label_response('MOS-1', rows) == [
        {'key': 'MOS-1', 'label': 'bug'},
        {'key': 'MOS-1', 'label': 'okr'},
    ]


async def test_convert_issue_response_groups_related_rows(
    db_session: sqlalchemy.ext.asyncio.AsyncSession,
    issue_create_factory: Callable[..., schemas.IssueCreate],
    seed_issue: Callable[..., Awaitable[None]],
    issue_rows_fetcher: Callable[..., Awaitable[list[models.IssueRow]]],
) -> None:
    await seed_issue(
        issue_create_factory(
            'MOS-1',
            status='In Progress',
            assignee='Ada',
            summary='first',
            description='description',
            priority=schemas.Priority.high,
            startdate=datetime.date(2026, 1, 6),
            timeestimate=datetime.timedelta(days=3),
            votes=8,
        ),
        components=['Platform', 'API'],
        labels=['okr', 'feature'],
    )
    await seed_issue(
        issue_create_factory(
            'MOS-2',
            status='Needs Triage',
            assignee=None,
            summary='second',
            description=None,
            priority=schemas.Priority.low,
            startdate=None,
            timeestimate=datetime.timedelta(days=1),
            votes=0,
        ),
        components=[],
        labels=['maintenance'],
    )
    await db_session.commit()

    rows = await issue_rows_fetcher()
    issues = models.convert_issue_response(rows)

    assert [issue.key for issue in issues] == ['MOS-1', 'MOS-2']
    assert issues[0].startdate == datetime.date(2026, 1, 6)
    assert issues[0].components == [
        schemas.Component(key='MOS-1', component='API'),
        schemas.Component(key='MOS-1', component='Platform'),
    ]
    assert issues[0].labels == [
        schemas.Label(key='MOS-1', label='feature'),
        schemas.Label(key='MOS-1', label='okr'),
    ]
    assert issues[1].assignee is None
    assert not issues[1].components


async def test_issue_get_filters_closed_assignee_and_needs_triage(
    db_session: sqlalchemy.ext.asyncio.AsyncSession,
    issue_create_factory: Callable[..., schemas.IssueCreate],
    seed_issue: Callable[..., Awaitable[None]],
) -> None:
    seeded = [
        (
            issue_create_factory('MOS-1', status='Closed', assignee='Ada'),
            ['API'],
            ['feature'],
        ),
        (
            issue_create_factory(
                'MOS-2',
                status='In Progress',
                assignee='Ada',
            ),
            ['API'],
            ['feature'],
        ),
        (
            issue_create_factory(
                'MOS-3',
                status='Needs Triage',
                assignee='Bob',
            ),
            ['API'],
            ['feature'],
        ),
        (
            issue_create_factory(
                'MOS-4',
                status='Backlog',
                assignee='Bob',
            ),
            [],
            ['feature'],
        ),
        (
            issue_create_factory(
                'MOS-5',
                status='Backlog',
                assignee='Bob',
            ),
            ['API'],
            [],
        ),
    ]
    for issue, components, labels in seeded:
        await seed_issue(issue, components=components, labels=labels)
    await db_session.commit()

    open_issues = await models.Issue.get(session=db_session)
    print(f'open issue keys={sorted(x.key for x in open_issues)}')
    assert sorted(issue.key for issue in open_issues) == [
        'MOS-2',
        'MOS-3',
        'MOS-4',
        'MOS-5',
    ]

    bob_issues = await models.Issue.get(assignee='Bob', session=db_session)
    assert sorted(issue.key for issue in bob_issues) == [
        'MOS-3',
        'MOS-4',
        'MOS-5',
    ]

    triage = await models.Issue.get(needs_triage=True, session=db_session)
    assert sorted(issue.key for issue in triage) == [
        'MOS-3',
        'MOS-4',
        'MOS-5',
    ]

    all_for_ada = await models.Issue.get(
        assignee='Ada',
        closed=True,
        session=db_session,
    )
    assert sorted(issue.key for issue in all_for_ada) == ['MOS-1', 'MOS-2']


async def test_issue_list_keys_returns_sorted_keys(
    db_session: sqlalchemy.ext.asyncio.AsyncSession,
    issue_create_factory: Callable[..., schemas.IssueCreate],
    seed_issue: Callable[..., Awaitable[None]],
) -> None:
    await seed_issue(
        issue_create_factory('MOS-3', status='In Progress', assignee='Ada'),
        components=['API'],
        labels=['feature'],
    )
    await seed_issue(
        issue_create_factory('MOS-1', status='Backlog', assignee='Ada'),
        components=['Platform'],
        labels=['bug'],
    )
    await seed_issue(
        issue_create_factory('MOS-2', status='Done', assignee='Ada'),
        components=['Client'],
        labels=['ops'],
    )
    await db_session.commit()

    tracked_keys = await models.Issue.list_keys(session=db_session)

    assert tracked_keys == ['MOS-1', 'MOS-2', 'MOS-3']


async def test_issue_hard_delete_removes_only_target_issue_graph(
    db_session: sqlalchemy.ext.asyncio.AsyncSession,
    issue_create_factory: Callable[..., schemas.IssueCreate],
    seed_issue: Callable[..., Awaitable[None]],
) -> None:
    await seed_issue(
        issue_create_factory('MOS-1', status='Backlog', assignee='Ada'),
        components=['Platform', 'API'],
        labels=['feature', 'maintenance'],
    )
    await seed_issue(
        issue_create_factory('MOS-2', status='In Progress', assignee='Bob'),
        components=['Client'],
        labels=['ops'],
    )
    await db_session.commit()

    await models.Issue.hard_delete('MOS-1', session=db_session)
    await db_session.commit()

    remaining_issues = await models.Issue.get(closed=True, session=db_session)
    component_rows = await db_session.execute(
        sqlalchemy.select(models.Component),
    )
    label_rows = await db_session.execute(
        sqlalchemy.select(models.Label),
    )
    components = component_rows.scalars().all()
    labels = label_rows.scalars().all()
    print(
        f'remaining issue keys={[x.key for x in remaining_issues]}, '
        f'components={[(x.key, x.component) for x in components]}, '
        f'labels={[(x.key, x.label) for x in labels]}',
    )

    issue_keys = [issue.key for issue in remaining_issues]
    component_pairs = [
        (component.key, component.component)
        for component in components
    ]
    label_pairs = [(label.key, label.label) for label in labels]

    assert issue_keys == ['MOS-2']
    assert component_pairs == [('MOS-2', 'Client')]
    assert label_pairs == [('MOS-2', 'ops')]


async def test_issue_upsert_updates_existing_issue(
    db_session: sqlalchemy.ext.asyncio.AsyncSession,
    issue_create_factory: Callable[..., schemas.IssueCreate],
    seed_issue: Callable[..., Awaitable[None]],
) -> None:
    await seed_issue(
        issue_create_factory(
            'MOS-9',
            status='Backlog',
            assignee='Ada',
            summary='before update',
            priority=schemas.Priority.low,
            votes=1,
        ),
        components=['Legacy'],
        labels=['legacy'],
    )
    await db_session.commit()

    await models.Issue.upsert(
        issue_create_factory(
            'MOS-9',
            status='In Progress',
            assignee='Bob',
            summary='after update',
            priority=schemas.Priority.high,
            votes=9,
            description='new',
            startdate=datetime.date(2026, 2, 1),
            timeestimate=datetime.timedelta(days=5),
        ),
        session=db_session,
    )
    await db_session.commit()

    fetched = await models.Issue.get(
        key='MOS-9',
        closed=True,
        session=db_session,
    )

    assert len(fetched) == 1
    assert fetched[0].summary == 'after update'
    assert fetched[0].assignee == 'Bob'
    assert fetched[0].priority == schemas.Priority.high
    assert fetched[0].votes == 9
    assert fetched[0].startdate == datetime.date(2026, 2, 1)

    rows = await db_session.execute(
        sqlalchemy.select(models.Issue).where(models.Issue.key == 'MOS-9'),
    )
    assert len(rows.scalars().all()) == 1


async def test_task_get_returns_utc_and_none_for_missing(
    db_session: sqlalchemy.ext.asyncio.AsyncSession,
) -> None:
    latest = datetime.datetime(2026, 2, 2, 10, 15, 0)
    await models.Task.upsert(
        schemas.Task(
            key='MOS',
            variant='open',
            latest=latest,
        ),
        session=db_session,
    )
    await db_session.commit()

    task = await models.Task.get('MOS', 'open', session=db_session)

    assert task is not None
    assert task.latest.tzinfo == datetime.UTC
    assert task.latest == latest.replace(tzinfo=datetime.UTC)

    missing = await models.Task.get('MOS', 'closed', session=db_session)
    assert missing is None
