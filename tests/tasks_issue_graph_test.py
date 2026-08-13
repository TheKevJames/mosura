import datetime
import types
from collections.abc import Awaitable
from collections.abc import Callable
from typing import Any

import fastapi
import sqlalchemy.ext.asyncio

from mosura import models
from mosura import schemas
from mosura import tasks


IssueFactory = Callable[..., dict[str, Any]]


class _FakeJiraClient:
    """
    Faithful-enough stand-in for the only Jira boundary the sync touches.

    Records changelog fetches so tests can assert on the real external effect
    (an extra Jira round-trip) rather than on private call counts.
    """

    def __init__(
        self,
        issues: list[dict[str, Any]],
        *,
        histories: list[dict[str, Any]] | None = None,
    ) -> None:
        self._issues = issues
        self._histories = histories or []
        self.changelog_fetches: list[str] = []

    def enhanced_search_issues(
        self, jql: str, **kwargs: Any,
    ) -> dict[str, Any]:
        _ = jql, kwargs
        return {'issues': self._issues, 'isLast': True}

    def issue(self, key: str, **kwargs: Any) -> object:
        _ = kwargs
        self.changelog_fetches.append(key)
        return types.SimpleNamespace(
            raw={'changelog': {'histories': self._histories}},
        )


def _build_app(
    jira_client: _FakeJiraClient,
    *,
    tracked_user_id: str = 'account-123',
    tracked_user_name: str = 'Alice',
) -> fastapi.FastAPI:
    app = fastapi.FastAPI()
    app.state.tracked_user_id = tracked_user_id
    app.state.tracked_user_name = tracked_user_name
    app.state.jira_client = jira_client
    return app


_STATUS_HISTORY = [
    {
        'created': '2026-01-05T10:00:00.000+0000',
        'items': [
            {
                'field': 'status',
                'fromString': 'To Do',
                'toString': 'In Progress',
            },
        ],
    },
]


async def _summary(
    db_session: sqlalchemy.ext.asyncio.AsyncSession,
    key: str,
) -> str | None:
    issues = await models.Issue.get(key=key, closed=True, session=db_session)
    return issues[0].summary if issues else None


async def test_unchanged_issue_skips_writes_and_changelog(
    db_session: sqlalchemy.ext.asyncio.AsyncSession,
    issue_create_factory: Callable[..., schemas.IssueCreate],
    seed_issue: Callable[..., Awaitable[None]],
    jira_raw_factory: IssueFactory,
) -> None:
    stored = datetime.datetime(2026, 1, 5, 10, 0, 0, tzinfo=datetime.UTC)
    await seed_issue(
        issue_create_factory(
            'MOS-1',
            status='In Progress',
            assignee='Alice',
            summary='stale summary',
            updated=stored,
        ),
    )
    await db_session.commit()

    jira_client = _FakeJiraClient(
        [
            jira_raw_factory(
                key='MOS-1',
                assignee='Alice',
                summary='fresh summary',
                updated='2026-01-05T10:00:00.000+0000',
            ),
        ],
        histories=_STATUS_HISTORY,
    )
    app = _build_app(jira_client)

    desired = await tasks.sync_desired_issues(app=app, session=db_session)
    await db_session.commit()

    assert desired == {'MOS-1'}
    # A skipped issue is not re-upserted, so the stale summary survives.
    assert await _summary(db_session, 'MOS-1') == 'stale summary'
    assert not jira_client.changelog_fetches


async def test_non_utc_offset_round_trips_and_skips_second_cycle(
    db_session: sqlalchemy.ext.asyncio.AsyncSession,
    jira_raw_factory: IssueFactory,
) -> None:
    # Real Jira returns ``updated`` in the caller's timezone, not UTC. A
    # store-then-fetch of the same instant must compare equal, otherwise every
    # issue looks changed on every poll. Drive two consecutive syncs off one
    # payload whose ``updated`` never advances and prove the second is a skip.
    payload = jira_raw_factory(
        key='MOS-1',
        assignee='Alice',
        summary='v1',
        updated='2026-01-05T05:00:00.000-0500',
    )
    jira_client = _FakeJiraClient([payload], histories=_STATUS_HISTORY)
    app = _build_app(jira_client)

    await tasks.sync_desired_issues(app=app, session=db_session)
    await db_session.commit()
    assert await _summary(db_session, 'MOS-1') == 'v1'

    # Same instant, new summary: a working gate skips the write entirely.
    payload['fields']['summary'] = 'v2'
    jira_client.changelog_fetches.clear()

    await tasks.sync_desired_issues(app=app, session=db_session)
    await db_session.commit()

    assert await _summary(db_session, 'MOS-1') == 'v1'
    assert not jira_client.changelog_fetches


async def test_changed_issue_resyncs_graph_and_transitions(
    db_session: sqlalchemy.ext.asyncio.AsyncSession,
    issue_create_factory: Callable[..., schemas.IssueCreate],
    seed_issue: Callable[..., Awaitable[None]],
    jira_raw_factory: IssueFactory,
) -> None:
    stored = datetime.datetime(2026, 1, 5, 10, 0, 0, tzinfo=datetime.UTC)
    await seed_issue(
        issue_create_factory(
            'MOS-1',
            status='In Progress',
            assignee='Alice',
            summary='stale summary',
            updated=stored,
        ),
    )
    await db_session.commit()

    jira_client = _FakeJiraClient(
        [
            jira_raw_factory(
                key='MOS-1',
                assignee='Alice',
                summary='fresh summary',
                updated='2026-01-06T10:00:00.000+0000',
            ),
        ],
        histories=_STATUS_HISTORY,
    )
    app = _build_app(jira_client)

    await tasks.sync_desired_issues(app=app, session=db_session)
    await db_session.commit()

    assert await _summary(db_session, 'MOS-1') == 'fresh summary'
    assert jira_client.changelog_fetches == ['MOS-1']
    transitions = await models.IssueTransition.get_by_keys(
        ['MOS-1'], session=db_session,
    )
    assert [t.to_status for t in transitions] == ['In Progress']


async def test_cold_start_fully_syncs_new_issue(
    db_session: sqlalchemy.ext.asyncio.AsyncSession,
    jira_raw_factory: IssueFactory,
) -> None:
    jira_client = _FakeJiraClient(
        [
            jira_raw_factory(
                key='MOS-1',
                assignee='Alice',
                summary='brand new',
                components=['API'],
                labels=['feature'],
                updated='2026-01-06T10:00:00.000+0000',
            ),
        ],
        histories=_STATUS_HISTORY,
    )
    app = _build_app(jira_client)

    await tasks.sync_desired_issues(app=app, session=db_session)
    await db_session.commit()

    issues = await models.Issue.get(key='MOS-1', session=db_session)
    assert len(issues) == 1
    assert issues[0].summary == 'brand new'
    assert [c.component for c in issues[0].components] == ['API']
    assert [label.label for label in issues[0].labels] == ['feature']
    assert jira_client.changelog_fetches == ['MOS-1']


async def test_non_tracked_user_never_fetches_changelog(
    db_session: sqlalchemy.ext.asyncio.AsyncSession,
    jira_raw_factory: IssueFactory,
) -> None:
    jira_client = _FakeJiraClient(
        [
            jira_raw_factory(
                key='MOS-1',
                assignee='Bob',
                summary='someone elses issue',
                updated='2026-01-06T10:00:00.000+0000',
            ),
        ],
        histories=_STATUS_HISTORY,
    )
    app = _build_app(jira_client)

    await tasks.sync_desired_issues(app=app, session=db_session)
    await db_session.commit()

    # The graph is still synced for non-tracked users, but their timelines
    # are never rendered, so the expensive changelog fetch is skipped.
    assert await _summary(db_session, 'MOS-1') == 'someone elses issue'
    assert not jira_client.changelog_fetches


async def test_stale_issue_pruned_by_reconciliation(
    db_session: sqlalchemy.ext.asyncio.AsyncSession,
    issue_create_factory: Callable[..., schemas.IssueCreate],
    seed_issue: Callable[..., Awaitable[None]],
    jira_raw_factory: IssueFactory,
) -> None:
    await seed_issue(
        issue_create_factory(
            'MOS-gone',
            status='In Progress',
            assignee='Alice',
        ),
    )
    await db_session.commit()

    jira_client = _FakeJiraClient(
        [
            jira_raw_factory(
                key='MOS-1',
                assignee='Alice',
                updated='2026-01-06T10:00:00.000+0000',
            ),
        ],
    )
    app = _build_app(jira_client)

    desired = await tasks.sync_desired_issues(app=app, session=db_session)
    pruned = await tasks.reconcile_stale_issues(
        session=db_session, desired_keys=desired,
    )
    await db_session.commit()

    assert pruned == {'MOS-gone'}
    assert await models.Issue.list_keys(session=db_session) == ['MOS-1']


async def test_naive_stored_timestamp_compares_against_aware_jira(
    db_session: sqlalchemy.ext.asyncio.AsyncSession,
    issue_create_factory: Callable[..., schemas.IssueCreate],
    seed_issue: Callable[..., Awaitable[None]],
    jira_raw_factory: IssueFactory,
) -> None:
    # SQLite hands back a naive datetime; Jira's timestamp is tz-aware. The
    # gate must normalise both and decide "unchanged" without raising.
    stored = datetime.datetime(2026, 1, 5, 10, 0, 0, tzinfo=datetime.UTC)
    await seed_issue(
        issue_create_factory(
            'MOS-1',
            status='In Progress',
            assignee='Alice',
            summary='stale summary',
            updated=stored,
        ),
    )
    await db_session.commit()

    jira_client = _FakeJiraClient(
        [
            jira_raw_factory(
                key='MOS-1',
                assignee='Alice',
                summary='fresh summary',
                updated='2026-01-05T10:00:00.000+0000',
            ),
        ],
    )
    app = _build_app(jira_client)

    await tasks.sync_desired_issues(app=app, session=db_session)
    await db_session.commit()

    assert await _summary(db_session, 'MOS-1') == 'stale summary'


def test_parse_changelog_keeps_original_jira_status_names() -> None:
    parse_changelog = getattr(tasks, '_parse_changelog')
    transitions = list(
        parse_changelog(
            {
                'changelog': {
                    'histories': [
                        {
                            'created': '2026-01-05T10:00:00.000+0000',
                            'items': [
                                {
                                    'field': 'status',
                                    'fromString': 'To Do',
                                    'toString': 'Done',
                                },
                            ],
                        },
                    ],
                },
            },
            'MOS-1',
        ),
    )

    assert len(transitions) == 1
    assert transitions[0].from_status == 'To Do'
    assert transitions[0].to_status == 'Done'


def test_parse_changelog_converts_non_utc_offset_to_utc() -> None:
    # A west-of-UTC offset must be converted, not relabelled: the instant
    # 2026-01-05T21:00-05:00 is 2026-01-06 in UTC, so the stored date must
    # land on the 6th to stay consistent with the issue's ``created`` date.
    parse_changelog = getattr(tasks, '_parse_changelog')
    transitions = list(
        parse_changelog(
            {
                'changelog': {
                    'histories': [
                        {
                            'created': '2026-01-05T21:00:00.000-0500',
                            'items': [
                                {
                                    'field': 'status',
                                    'fromString': 'Open',
                                    'toString': 'Needs Triage',
                                },
                            ],
                        },
                    ],
                },
            },
            'MOS-1',
        ),
    )

    assert len(transitions) == 1
    assert transitions[0].timestamp == datetime.datetime(
        2026, 1, 6, 2, 0, 0, tzinfo=datetime.UTC,
    )
