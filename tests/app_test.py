import asyncio
import types
import unittest.mock
import warnings

import fastapi
import httpx
import pytest

import mosura.app
from mosura import config
from mosura import database


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

    assert resolved == 'account-123'
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
    app.state.tracked_user_id = 'acct-2'
    app.state.jira_client = types.SimpleNamespace(
        search_users=unittest.mock.Mock(
            return_value=[
                types.SimpleNamespace(accountId='acct-1', displayName='Alice'),
                types.SimpleNamespace(accountId='acct-2', displayName='Bob'),
            ],
        ),
    )

    resolved = mosura.app.resolve_tracked_user(app)

    assert resolved == 'Bob'


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
        mosura_custom_jql='labels = triage',
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
            return_value='account-123',
        ),
    )
    monkeypatch.setattr(
        mosura.app,
        'resolve_tracked_assignee',
        unittest.mock.Mock(
            return_value='Alice Example',
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
