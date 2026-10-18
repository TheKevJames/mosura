# pylint: disable=protected-access
import datetime
import types
from collections.abc import Awaitable
from collections.abc import Callable
from typing import cast

import fastapi
import pytest
import sqlalchemy.ext.asyncio

from mosura import models
from mosura import schemas
from mosura import ui

CURRENT_DATE = datetime.date(2026, 3, 4)


def _utc(*args: int) -> datetime.datetime:
    return datetime.datetime(*args, tzinfo=datetime.UTC)


@pytest.fixture(scope='function', name='seeded')
async def fixture_seeded(
    db_session: sqlalchemy.ext.asyncio.AsyncSession,
    issue_create_factory: Callable[..., schemas.IssueCreate],
    transition_factory: Callable[..., schemas.IssueTransition],
    seed_issue: Callable[..., Awaitable[None]],
) -> None:
    # (key, status, created, updated, timeestimate days, startdate,
    #  transition to_status/timestamp)
    rows: list[
        tuple[
            str,
            str,
            datetime.datetime,
            datetime.datetime,
            int,
            datetime.date | None,
            tuple[str, datetime.datetime] | None,
        ]
    ] = [
        (
            'CLOSED-NO-TRANS',
            'Closed',
            _utc(2025, 12, 1),
            _utc(2026, 1, 12, 9),
            3,
            None,
            None,
        ),
        (
            'CLOSED-TRANS',
            'Closed',
            _utc(2025, 12, 1),
            _utc(2026, 1, 11, 10),
            3,
            None,
            ('Closed', _utc(2026, 1, 11, 10)),
        ),
        (
            'CLOSED-RECENT',
            'Closed',
            _utc(2026, 2, 20),
            _utc(2026, 3, 3, 12),
            3,
            None,
            ('Closed', _utc(2026, 3, 3, 11)),
        ),
        (
            'OPEN-NO-ESTIMATE',
            'In Progress',
            _utc(2025, 6, 1),
            _utc(2025, 6, 2),
            0,
            None,
            None,
        ),
        (
            'OPEN-OVERDUE-START',
            'Backlog',
            _utc(2025, 6, 1),
            _utc(2025, 6, 2),
            5,
            datetime.date(2025, 7, 1),
            None,
        ),
        (
            'OPEN-RUNNING',
            'Code Review',
            _utc(2025, 11, 1),
            _utc(2025, 11, 3),
            30,
            datetime.date(2025, 11, 2),
            ('In Progress', _utc(2025, 11, 3)),
        ),
    ]
    for key, status, created, updated, days, startdate, trans in rows:
        await seed_issue(
            issue_create_factory(
                key,
                status=status,
                assignee='Ada',
                created=created,
                updated=updated,
                timeestimate=datetime.timedelta(days=days),
                startdate=startdate,
            )
        )
        if trans:
            await models.IssueTransition.upsert(
                transition_factory(
                    key=key,
                    from_status='In Progress',
                    to_status=trans[0],
                    timestamp=trans[1],
                ),
                session=db_session,
            )
    await db_session.commit()


async def _unfiltered_timeline(
    session: sqlalchemy.ext.asyncio.AsyncSession, selected_date: datetime.date
) -> schemas.Timeline:
    issues = await models.Issue.get(
        assignee='Ada', closed=True, session=session
    )
    transitions: dict[str, list[schemas.IssueTransition]] = {}
    for transition in await models.IssueTransition.get_by_keys(
        [issue.key for issue in issues], session=session
    ):
        transitions.setdefault(transition.key, []).append(transition)

    timeline = schemas.Timeline.from_issues(
        issues,
        selected_date=selected_date,
        current_date=CURRENT_DATE,
        transitions=transitions,
        weeks_before=1,
        weeks_after=1,
    )
    ui._enrich_timeline_for_template(timeline, current_date=CURRENT_DATE)
    return timeline


@pytest.mark.usefixtures('seeded')
@pytest.mark.parametrize(
    ('selected_date', 'expected_loaded'),
    [
        (
            datetime.date(2026, 1, 13),
            {'CLOSED-NO-TRANS', 'CLOSED-TRANS', 'CLOSED-RECENT'},
        ),
        (datetime.date(2026, 1, 19), {'CLOSED-NO-TRANS', 'CLOSED-RECENT'}),
        (datetime.date(2026, 1, 26), {'CLOSED-RECENT'}),
        (CURRENT_DATE, {'CLOSED-RECENT'}),
        (datetime.date(2026, 3, 18), set()),
    ],
)
async def test_build_timeline_prefilter_matches_unfiltered_timeline(
    db_session: sqlalchemy.ext.asyncio.AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    selected_date: datetime.date,
    expected_loaded: set[str],
) -> None:
    loaded: set[str] = set()
    original_get_by_keys = models.IssueTransition.get_by_keys

    async def _spy_get_by_keys(
        keys: list[str], *, session: sqlalchemy.ext.asyncio.AsyncSession
    ) -> list[schemas.IssueTransition]:
        loaded.update(keys)
        return await original_get_by_keys(keys, session=session)

    monkeypatch.setattr(
        models.IssueTransition, 'get_by_keys', _spy_get_by_keys
    )
    request = types.SimpleNamespace(
        app=types.SimpleNamespace(
            state=types.SimpleNamespace(tracked_user_name='Ada')
        )
    )

    timeline = await ui._build_timeline(
        cast(fastapi.Request, request),
        db_session,
        selected_date,
        CURRENT_DATE,
        weeks_before=1,
        weeks_after=1,
    )
    loaded_closed = {key for key in loaded if key.startswith('CLOSED-')}
    print(f'loaded closed={sorted(loaded_closed)} timeline={timeline!r}')

    assert loaded_closed == expected_loaded
    assert timeline == await _unfiltered_timeline(db_session, selected_date)
