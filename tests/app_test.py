import asyncio
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
    triage_issues: list[schemas.Issue],
) -> Callable[..., list[schemas.Issue]]:
    """Build a mock for ``models.Issue.get`` that dispatches on kwargs."""

    async def _get(
        **kwargs: object,
    ) -> list[schemas.Issue]:
        if kwargs.get('assignee'):
            return my_issues.copy()
        if kwargs.get('needs_triage'):
            return triage_issues.copy()
        return []

    return _get  # type: ignore[return-value]


@pytest.mark.usefixtures('api_session')
async def test_home_returns_200_with_section_headings(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    issue_factory: Callable[..., schemas.Issue],
) -> None:
    my = [issue_factory('MY-1', assignee='TestUser')]
    triage = [issue_factory('TRI-1', status='Needs Triage')]
    monkeypatch.setattr(
        models.Issue, 'get', _mock_issue_get(
            my_issues=my, triage_issues=triage,
        ),
    )
    mosura.app.app.state.tracked_user_name = 'TestUser'

    response = await client.get('/')

    assert response.status_code == 200
    html = response.text
    print(f'Response contains {len(html)} chars')
    assert 'My Issues (Top 5)' in html
    assert 'Needs Triage' in html


@pytest.mark.usefixtures('api_session')
async def test_home_limits_my_issues_to_5(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    issue_factory: Callable[..., schemas.Issue],
) -> None:
    my = [issue_factory(f'MY-{i}', assignee='TestUser') for i in range(8)]
    monkeypatch.setattr(
        models.Issue, 'get', _mock_issue_get(
            my_issues=my, triage_issues=[],
        ),
    )
    mosura.app.app.state.tracked_user_name = 'TestUser'

    response = await client.get('/')

    html = response.text
    # Count unique issue keys rendered in the "my issues" table
    my_keys_found = sorted(set(re.findall(r'MY-\d+', html)))
    print(f'Found {len(my_keys_found)} unique my-issue keys: {my_keys_found}')
    assert len(my_keys_found) <= 5


@pytest.mark.usefixtures('api_session')
async def test_home_limits_triage_to_10(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    issue_factory: Callable[..., schemas.Issue],
) -> None:
    triage = [
        issue_factory(f'TRI-{i}', status='Needs Triage') for i in range(15)
    ]
    monkeypatch.setattr(
        models.Issue, 'get', _mock_issue_get(
            my_issues=[], triage_issues=triage,
        ),
    )
    mosura.app.app.state.tracked_user_name = 'TestUser'

    response = await client.get('/')

    html = response.text
    triage_keys_found = sorted(set(re.findall(r'TRI-\d+', html)))
    print(
        f'Found {len(triage_keys_found)} unique triage keys: '
        f'{triage_keys_found}',
    )
    assert len(triage_keys_found) <= 10


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
            my_issues=my, triage_issues=[],
        ),
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
            my_issues=[], triage_issues=[],
        ),
    )
    mosura.app.app.state.tracked_user_name = 'TestUser'

    response = await client.get('/')

    html = response.text
    print(f'Empty state HTML length: {len(html)}')
    assert 'No issues assigned' in html
    assert 'Nothing to triage' in html
