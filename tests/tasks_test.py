import asyncio
import contextlib
import types
import unittest.mock
from collections.abc import AsyncIterator
from collections.abc import Callable
from typing import Any
from typing import cast

import fastapi
import pytest
import requests

from mosura import database
from mosura import models
from mosura import tasks


IssueFactory = Callable[..., dict[str, Any]]


def _patch_fetch_loop(
    monkeypatch: pytest.MonkeyPatch,
    *,
    sync_side_effect: list[Any],
    sleep_side_effect: Any = None,
) -> unittest.mock.AsyncMock:
    """Neutralise timing/db so a ``fetch_desired`` run is driven by mocks."""
    @contextlib.asynccontextmanager
    async def fake_session_from_app(
        _app: fastapi.FastAPI,
    ) -> AsyncIterator[object]:
        yield object()

    sync_once = unittest.mock.AsyncMock(side_effect=sync_side_effect)
    monkeypatch.setattr(database, 'session_from_app', fake_session_from_app)
    monkeypatch.setattr(
        models.Task, 'get', unittest.mock.AsyncMock(return_value=None),
    )
    monkeypatch.setattr(tasks, '_sync_once', sync_once)
    monkeypatch.setattr(
        asyncio, 'sleep',
        unittest.mock.AsyncMock(side_effect=sleep_side_effect),
    )
    return sync_once


def _build_app(
    *,
    tracked_user_id: str = 'account-123',
    tracked_user_name: str = 'Test User',
) -> fastapi.FastAPI:
    app = fastapi.FastAPI()
    app.state.settings = types.SimpleNamespace(
        mosura_poll_interval=60,
    )
    app.state.tracked_user_id = tracked_user_id
    app.state.tracked_user_name = tracked_user_name
    app.state.jira_client = types.SimpleNamespace()
    return app


async def test_sync_desired_issues_appends_custom_jql(
    monkeypatch: pytest.MonkeyPatch,
    jira_raw_factory: IssueFactory,
) -> None:
    app = _build_app()
    session = object()

    search = unittest.mock.AsyncMock(
        return_value=[jira_raw_factory(key='MOS-101')],
    )
    upsert = unittest.mock.AsyncMock()
    setting_get = unittest.mock.AsyncMock(return_value='project = OPS')
    updated_map = unittest.mock.AsyncMock(return_value={})

    monkeypatch.setattr(tasks, '_search_issues', search)
    monkeypatch.setattr(tasks, '_upsert_issue_graph', upsert)
    monkeypatch.setattr(models.Setting, 'get', setting_get)
    monkeypatch.setattr(models.Issue, 'get_updated_map', updated_map)

    desired = await tasks.sync_desired_issues(app=app, session=session)

    assert desired == {'MOS-101'}
    assert search.await_args_list == [
        unittest.mock.call(
            jira_client=app.state.jira_client,
            jql='(assignee = "account-123")OR(project = OPS)',
        ),
    ]
    assert [call.args[0]['key'] for call in upsert.await_args_list] == [
        'MOS-101',
    ]


async def test_reconcile_stale_issues_deletes_stale_without_refetch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = object()

    list_keys = unittest.mock.AsyncMock(
        return_value=['OPS-9', 'MOS-2', 'MOS-1'],
    )
    final_fetch = unittest.mock.AsyncMock()
    upsert = unittest.mock.AsyncMock()
    hard_delete = unittest.mock.AsyncMock()

    monkeypatch.setattr(models.Issue, 'list_keys', list_keys)
    monkeypatch.setattr(tasks, '_fetch_issue_by_key', final_fetch)
    monkeypatch.setattr(tasks, '_upsert_issue_graph', upsert)
    monkeypatch.setattr(models.Issue, 'hard_delete', hard_delete)

    stale = await tasks.reconcile_stale_issues(
        session=session,
        desired_keys={'MOS-2'},
    )

    assert stale == {'MOS-1', 'OPS-9'}
    final_fetch.assert_not_awaited()
    upsert.assert_not_awaited()
    assert hard_delete.await_args_list == [
        unittest.mock.call('MOS-1', session=session),
        unittest.mock.call('OPS-9', session=session),
    ]


async def test_reconcile_stale_issues_deletes_single_stale_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = object()

    list_keys = unittest.mock.AsyncMock(return_value=['MOS-404'])
    hard_delete = unittest.mock.AsyncMock()

    monkeypatch.setattr(models.Issue, 'list_keys', list_keys)
    monkeypatch.setattr(models.Issue, 'hard_delete', hard_delete)

    stale = await tasks.reconcile_stale_issues(
        session=session,
        desired_keys=set(),
    )

    assert stale == {'MOS-404'}
    hard_delete.assert_awaited_once_with('MOS-404', session=session)


async def test_reconcile_stale_issues_keeps_desired_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = object()

    list_keys = unittest.mock.AsyncMock(return_value=['MOS-1', 'OPS-9'])
    hard_delete = unittest.mock.AsyncMock()

    monkeypatch.setattr(models.Issue, 'list_keys', list_keys)
    monkeypatch.setattr(models.Issue, 'hard_delete', hard_delete)

    stale = await tasks.reconcile_stale_issues(
        session=session,
        desired_keys={'OPS-9'},
    )

    assert stale == {'MOS-1'}
    hard_delete.assert_awaited_once_with('MOS-1', session=session)


async def test_reconcile_stale_issues_noops_when_no_stale_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = object()

    list_keys = unittest.mock.AsyncMock(return_value=['MOS-1', 'MOS-2'])
    hard_delete = unittest.mock.AsyncMock()

    monkeypatch.setattr(models.Issue, 'list_keys', list_keys)
    monkeypatch.setattr(models.Issue, 'hard_delete', hard_delete)

    stale = await tasks.reconcile_stale_issues(
        session=session,
        desired_keys={'MOS-1', 'MOS-2'},
    )

    assert not stale
    hard_delete.assert_not_awaited()


async def test_fetch_desired_crashes_after_three_transient_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _build_app()
    sync_once = _patch_fetch_loop(
        monkeypatch,
        sync_side_effect=[
            requests.exceptions.ConnectionError(),
            requests.exceptions.ConnectionError(),
            requests.exceptions.ConnectionError(),
        ],
    )

    with pytest.raises(requests.exceptions.ConnectionError):
        await tasks.fetch_desired(app)

    assert sync_once.await_count == 3


async def test_fetch_desired_survives_transient_failures_below_threshold(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _build_app()
    # A success between transient failures must reset the streak: without the
    # reset this pattern would hit three in a row and crash.
    sync_once = _patch_fetch_loop(
        monkeypatch,
        sync_side_effect=[
            requests.exceptions.ConnectionError(),
            requests.exceptions.ConnectionError(),
            None,
            requests.exceptions.ConnectionError(),
            requests.exceptions.ConnectionError(),
        ],
        sleep_side_effect=[None, None, None, None, asyncio.CancelledError()],
    )

    with pytest.raises(asyncio.CancelledError):
        await tasks.fetch_desired(app)

    assert sync_once.await_count == 5


async def test_fetch_desired_crashes_immediately_on_non_transient(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _build_app()
    sync_once = _patch_fetch_loop(
        monkeypatch,
        sync_side_effect=[ValueError('boom')],
    )

    with pytest.raises(ValueError, match='boom'):
        await tasks.fetch_desired(app)

    assert sync_once.await_count == 1


async def test_spawn_creates_single_desired_worker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _build_app()
    app.state.jira_client.project = unittest.mock.Mock()

    fetched: list[fastapi.FastAPI] = []

    def fake_fetch_desired(
        app_: fastapi.FastAPI,
    ) -> object:
        fetched.append(app_)
        return 'desired'

    created: list[asyncio.Task[None]] = []

    def fake_create_task(
        _payload: object,
        *,
        name: str,
    ) -> asyncio.Task[None]:
        assert name == 'fetch_desired'
        task = cast(
            asyncio.Task[None],
            unittest.mock.Mock(spec=asyncio.Task),
        )
        created.append(task)
        return task

    create_task = unittest.mock.Mock(side_effect=fake_create_task)

    monkeypatch.setattr(tasks, 'fetch_desired', fake_fetch_desired)
    monkeypatch.setattr(asyncio, 'create_task', create_task)

    spawned = await tasks.spawn(app)

    assert len(spawned) == 1
    assert spawned == set(created)
    assert len(fetched) == 1
    assert fetched[0] is app
    app.state.jira_client.project.assert_not_called()
