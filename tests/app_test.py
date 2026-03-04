# pylint: disable=too-many-lines
import asyncio
import datetime
import re
import types
import unittest.mock
import warnings
from collections.abc import Callable

import fastapi
import httpx
import pytest

import mosura.app
from mosura import config
from mosura import database
from mosura import models
from mosura import schemas


async def test_root(client: httpx.AsyncClient) -> None:
    response = await client.get('/api/v0/ping')

    assert response.status_code == 204


def test_resolve_tracked_user_falls_back_to_jira_auth_user() -> None:
    app = fastapi.FastAPI()
    with warnings.catch_warnings():
        warnings.simplefilter('ignore', UserWarning)
        app.state.settings = config.Settings(
            jira_auth_token='test-token',
            jira_auth_user='auth@example.com',
            jira_domain='https://jira.example.com',
            mosura_user=None,
        )
    app.state.jira_client = types.SimpleNamespace(
        search_users=unittest.mock.Mock(
            return_value=[types.SimpleNamespace(accountId='account-123')],
        ),
    )

    resolved = mosura.app.resolve_tracked_user(app)

    assert resolved.accountId == 'account-123'
    app.state.jira_client.search_users.assert_called_once_with(
        query='auth@example.com',
    )


def test_resolve_tracked_user_raises_on_ambiguous_matches() -> None:
    app = fastapi.FastAPI()
    app.state.settings = types.SimpleNamespace(jira_tracked_user='alice')
    app.state.jira_client = types.SimpleNamespace(
        search_users=unittest.mock.Mock(
            return_value=[
                types.SimpleNamespace(accountId='acct-1'),
                types.SimpleNamespace(accountId='acct-2'),
            ],
        ),
    )

    with pytest.raises(RuntimeError, match='is ambiguous'):
        mosura.app.resolve_tracked_user(app)


def test_resolve_tracked_user_prefers_matching_account_id() -> None:
    app = fastapi.FastAPI()
    app.state.settings = types.SimpleNamespace(jira_tracked_user='acct-2')
    app.state.jira_client = types.SimpleNamespace(
        search_users=unittest.mock.Mock(
            return_value=[
                types.SimpleNamespace(accountId='acct-1', displayName='Alice'),
                types.SimpleNamespace(accountId='acct-2', displayName='Bob'),
            ],
        ),
    )

    resolved = mosura.app.resolve_tracked_user(app)

    assert resolved.displayName == 'Bob'


async def test_lifespan_fails_fast_if_tracked_user_is_unresolvable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = types.SimpleNamespace(jira_tracked_user='missing-user')
    jira_client = types.SimpleNamespace(
        search_users=unittest.mock.Mock(return_value=[]),
    )
    load_settings = unittest.mock.Mock(return_value=settings)
    from_settings = unittest.mock.Mock(return_value=jira_client)
    build_engine = unittest.mock.Mock()

    monkeypatch.setattr(config, 'load_settings', load_settings)
    monkeypatch.setattr(config.Jira, 'from_settings', from_settings)
    monkeypatch.setattr(database, 'build_engine', build_engine)

    with pytest.raises(
        RuntimeError,
        match='could not resolve tracked Jira user "missing-user"',
    ):
        async with mosura.app.lifespan(fastapi.FastAPI()):
            pass

    build_engine.assert_not_called()


async def test_lifespan_starts_background_tasks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = fastapi.FastAPI()
    settings = types.SimpleNamespace(
        jira_tracked_user='account-123',
    )
    jira_client = types.SimpleNamespace()

    class FakeConn:
        async def run_sync(self, _func: object) -> None:
            return None

    class FakeBeginContext:
        async def __aenter__(self) -> FakeConn:
            return FakeConn()

        async def __aexit__(
            self,
            _exc_type: object,
            _exc: object,
            _tb: object,
        ) -> None:
            return None

    class FakeEngine:
        def begin(self) -> FakeBeginContext:
            return FakeBeginContext()

        async def dispose(self) -> None:
            return None

    background_task = asyncio.create_task(asyncio.sleep(3600))
    spawn = unittest.mock.AsyncMock(return_value={background_task})

    monkeypatch.setattr(
        config,
        'load_settings',
        unittest.mock.Mock(
            return_value=settings,
        ),
    )
    monkeypatch.setattr(
        config.Jira,
        'from_settings',
        unittest.mock.Mock(
            return_value=jira_client,
        ),
    )
    monkeypatch.setattr(
        mosura.app,
        'resolve_tracked_user',
        unittest.mock.Mock(
            return_value=types.SimpleNamespace(
                accountId='account-123',
                displayName='Alice Example',
            ),
        ),
    )
    monkeypatch.setattr(
        database,
        'build_engine',
        unittest.mock.Mock(
            return_value=FakeEngine(),
        ),
    )
    monkeypatch.setattr(database, 'build_sessionmaker', unittest.mock.Mock())
    monkeypatch.setattr('mosura.app.tasks.spawn', spawn)

    async with mosura.app.lifespan(app):
        pass

    assert spawn.await_count == 1
    assert spawn.await_args is not None
    assert spawn.await_args.args == (app,)


# -- Homepage dashboard tests --


def _mock_issue_get(
    *,
    my_issues: list[schemas.Issue],
    timeline_issues: list[schemas.Issue] | None = None,
) -> Callable[..., list[schemas.Issue]]:
    """
    Build a mock for ``models.Issue.get`` that dispatches on kwargs.

    Handles two calls in home():
    - assignee=..., closed=False -> my_issues
    - assignee=..., closed=True -> timeline_issues
    """
    if timeline_issues is None:
        timeline_issues = []

    async def _get(
        **kwargs: object,
    ) -> list[schemas.Issue]:
        # Handle assignee + closed combination
        if kwargs.get('assignee'):
            if kwargs.get('closed') is False:
                return my_issues.copy()
            if kwargs.get('closed') is True:
                return timeline_issues.copy()
        # Handle needs_triage (legacy, should not be called in new
        # implementation)
        if kwargs.get('needs_triage'):
            return []
        return []

    return _get  # type: ignore[return-value]


@pytest.mark.usefixtures('api_session')
async def test_home_returns_200_with_section_headings(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    issue_factory: Callable[..., schemas.Issue],
) -> None:
    my = [issue_factory('MY-1', assignee='TestUser')]
    timeline_issues = [
        issue_factory(
            'TL-1',
            status='In Progress',
            assignee='TestUser',
        ),
    ]
    monkeypatch.setattr(
        models.Issue, 'get', _mock_issue_get(
            my_issues=my, timeline_issues=timeline_issues,
        ),
    )
    monkeypatch.setattr(
        models.IssueTransition, 'get_by_keys',
        unittest.mock.AsyncMock(return_value=[]),
    )
    mosura.app.app.state.tracked_user_name = 'TestUser'

    response = await client.get('/')

    assert response.status_code == 200
    html = response.text
    print(f'Response contains {len(html)} chars')
    assert 'My Issues (Top 5)' in html
    assert 'Timeline' in html
    assert '/timeline' in html


@pytest.mark.usefixtures('api_session')
async def test_home_limits_my_issues_to_5(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    issue_factory: Callable[..., schemas.Issue],
) -> None:
    my = [issue_factory(f'MY-{i}', assignee='TestUser') for i in range(8)]
    monkeypatch.setattr(
        models.Issue, 'get', _mock_issue_get(
            my_issues=my, timeline_issues=[],
        ),
    )
    monkeypatch.setattr(
        models.IssueTransition, 'get_by_keys',
        unittest.mock.AsyncMock(return_value=[]),
    )
    mosura.app.app.state.tracked_user_name = 'TestUser'

    response = await client.get('/')

    html = response.text
    # Count unique issue keys rendered in the "my issues" table
    my_keys_found = sorted(set(re.findall(r'MY-\d+', html)))
    print(f'Found {len(my_keys_found)} unique my-issue keys: {my_keys_found}')
    assert len(my_keys_found) <= 5


@pytest.mark.usefixtures('api_session')
async def test_home_sorts_my_issues_by_priority_descending(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    issue_factory: Callable[..., schemas.Issue],
) -> None:
    my = [
        issue_factory('MY-L', priority=schemas.Priority.low),
        issue_factory('MY-U', priority=schemas.Priority.urgent),
        issue_factory('MY-M', priority=schemas.Priority.medium),
        issue_factory('MY-N', priority=schemas.Priority.unknown),
        issue_factory('MY-H', priority=schemas.Priority.high),
    ]
    monkeypatch.setattr(
        models.Issue, 'get', _mock_issue_get(
            my_issues=my, timeline_issues=[],
        ),
    )
    monkeypatch.setattr(
        models.IssueTransition, 'get_by_keys',
        unittest.mock.AsyncMock(return_value=[]),
    )
    mosura.app.app.state.tracked_user_name = 'TestUser'

    response = await client.get('/')

    html = response.text
    # Find the order of issue keys in the rendered HTML
    positions = {
        key: html.index(key) for key in [
            'MY-U', 'MY-H', 'MY-M', 'MY-L', 'MY-N',
        ]
    }
    print(f'Priority order positions: {positions}')
    assert positions['MY-U'] < positions['MY-H']
    assert positions['MY-H'] < positions['MY-M']
    assert positions['MY-M'] < positions['MY-L']
    assert positions['MY-L'] < positions['MY-N']


@pytest.mark.usefixtures('api_session')
async def test_home_empty_states(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        models.Issue, 'get', _mock_issue_get(
            my_issues=[], timeline_issues=[],
        ),
    )
    monkeypatch.setattr(
        models.IssueTransition, 'get_by_keys',
        unittest.mock.AsyncMock(return_value=[]),
    )
    mosura.app.app.state.tracked_user_name = 'TestUser'

    response = await client.get('/')

    html = response.text
    print(f'Empty state HTML length: {len(html)}')
    assert 'No issues assigned' in html
    assert 'No issues found in this week.' in html


@pytest.mark.usefixtures('api_session')
async def test_home_timeline_renders_gantt_chart(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    issue_factory: Callable[..., schemas.Issue],
    transition_factory: Callable[..., schemas.IssueTransition],
) -> None:
    issue = issue_factory(
        'HM-1',
        status='In Progress',
        assignee='TestUser',
        startdate=datetime.date(2026, 3, 2),
        created=datetime.datetime(
            2026, 3, 1, 0, 0, 0, tzinfo=datetime.UTC,
        ),
        updated=datetime.datetime(
            2026, 3, 4, 8, 0, 0, tzinfo=datetime.UTC,
        ),
        timeestimate=datetime.timedelta(days=5),
    )
    transitions = [
        transition_factory(
            key='HM-1',
            from_status='Backlog',
            to_status='In Progress',
            timestamp=datetime.datetime(
                2026, 3, 2, 10, 0, 0, tzinfo=datetime.UTC,
            ),
        ),
    ]

    monkeypatch.setattr(
        models.Issue, 'get', _mock_issue_get(
            my_issues=[], timeline_issues=[issue],
        ),
    )
    monkeypatch.setattr(
        models.IssueTransition, 'get_by_keys',
        unittest.mock.AsyncMock(return_value=transitions),
    )
    mosura.app.app.state.tracked_user_name = 'TestUser'

    response = await client.get('/')

    assert response.status_code == 200
    html = response.text
    # Verify gantt chart class is present
    assert 'gantt-chart' in html
    # Verify segment CSS class for status is rendered
    assert 'status-in-progress' in html
    # Verify no date navigation controls
    assert 'timeline-picker-link' not in html


@pytest.mark.usefixtures('api_session')
async def test_home_timeline_has_no_date_navigation(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    issue_factory: Callable[..., schemas.Issue],
) -> None:
    issue = issue_factory(
        'NAV-1',
        status='Ready for Testing',
        assignee='TestUser',
    )
    monkeypatch.setattr(
        models.Issue, 'get', _mock_issue_get(
            my_issues=[], timeline_issues=[issue],
        ),
    )
    monkeypatch.setattr(
        models.IssueTransition, 'get_by_keys',
        unittest.mock.AsyncMock(return_value=[]),
    )
    mosura.app.app.state.tracked_user_name = 'TestUser'

    response = await client.get('/')

    assert response.status_code == 200
    html = response.text
    # Verify no timeline-picker-link elements (date navigation controls)
    assert html.count('timeline-picker-link') == 0


@pytest.mark.usefixtures('api_session')
async def test_timeline_header_shows_full_range(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    issue_get = unittest.mock.AsyncMock(return_value=[])
    monkeypatch.setattr(models.Issue, 'get', issue_get)
    mosura.app.app.state.tracked_user_name = 'TestUser'

    response = await client.get('/timeline?date=2026-03-02')

    assert response.status_code == 200
    html = response.text
    assert '2026-02-09 - 2026-04-13' in html
    # Timeline has 4 navigation links: prev month, prev week, next week, next
    # month
    assert html.count('class="timeline-picker-link"') == 4


@pytest.mark.usefixtures('api_session')
async def test_timeline_uses_issue_transitions_for_segments(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    issue_factory: Callable[..., schemas.Issue],
    transition_factory: Callable[..., schemas.IssueTransition],
) -> None:
    issue = issue_factory(
        'DP-172445',
        status='Ready for Testing',
        assignee='TestUser',
        startdate=None,
        created=datetime.datetime(
            2026, 1, 20, 10, 0, 0, tzinfo=datetime.UTC,
        ),
        updated=datetime.datetime(
            2026, 3, 4, 7, 42, 1, tzinfo=datetime.UTC,
        ),
        timeestimate=datetime.timedelta(days=14),
    )
    transitions = [
        transition_factory(
            key='DP-172445',
            from_status='Needs Triage',
            to_status='In Progress',
            timestamp=datetime.datetime(
                2026, 2, 23, 11, 25, 40, tzinfo=datetime.UTC,
            ),
        ),
        transition_factory(
            key='DP-172445',
            from_status='In Progress',
            to_status='Code Review',
            timestamp=datetime.datetime(
                2026, 3, 2, 7, 48, 56, tzinfo=datetime.UTC,
            ),
        ),
        transition_factory(
            key='DP-172445',
            from_status='Code Review',
            to_status='Ready for Testing',
            timestamp=datetime.datetime(
                2026, 3, 2, 7, 50, 3, tzinfo=datetime.UTC,
            ),
        ),
    ]

    issue_get = unittest.mock.AsyncMock(return_value=[issue])
    transition_get = unittest.mock.AsyncMock(return_value=transitions)
    monkeypatch.setattr(models.Issue, 'get', issue_get)
    monkeypatch.setattr(
        models.IssueTransition,
        'get_by_keys',
        transition_get,
    )
    mosura.app.app.state.tracked_user_name = 'TestUser'

    response = await client.get('/timeline?date=2026-03-04')

    assert response.status_code == 200
    transition_get.assert_awaited_once()
    html = response.text
    assert 'status-needs-triage' in html
    assert 'status-in-progress' in html
    assert 'status-ready-for-testing' not in html
    assert 'title="Code Review: 2026-03-02 to 2026-03-02"' in html
    assert 'title="Ready for Testing: 2026-03-02 to 2026-03-08"' in html
    assert html.count('has-transition-marker') >= 2


@pytest.mark.usefixtures('api_session')
async def test_timeline_overdue_tooltip_includes_status(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    issue_factory: Callable[..., schemas.Issue],
) -> None:
    issue = issue_factory(
        'OVER-1',
        status='In Progress',
        assignee='TestUser',
        startdate=datetime.date(2026, 3, 1),
        created=datetime.datetime(
            2026, 2, 20, 10, 0, 0, tzinfo=datetime.UTC,
        ),
        updated=datetime.datetime(
            2026, 3, 4, 8, 0, 0, tzinfo=datetime.UTC,
        ),
        timeestimate=datetime.timedelta(days=1),
    )

    issue_get = unittest.mock.AsyncMock(return_value=[issue])
    transition_get = unittest.mock.AsyncMock(return_value=[])
    monkeypatch.setattr(models.Issue, 'get', issue_get)
    monkeypatch.setattr(
        models.IssueTransition,
        'get_by_keys',
        transition_get,
    )
    mosura.app.app.state.tracked_user_name = 'TestUser'

    response = await client.get('/timeline?date=2026-03-04')

    assert response.status_code == 200
    html = response.text
    assert 'title="In Progress: overdue since 2026-03-01"' in html
