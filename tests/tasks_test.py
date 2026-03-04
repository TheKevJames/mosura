import asyncio
import types
import unittest.mock
from collections.abc import Callable
from typing import Any
from typing import cast

import fastapi
import pytest

from mosura import models
from mosura import tasks


IssueFactory = Callable[..., dict[str, Any]]


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


async def test_sync_desired_issues_without_custom_jql(
    monkeypatch: pytest.MonkeyPatch,
    jira_raw_factory: IssueFactory,
) -> None:
    app = _build_app()
    session = object()

    search = unittest.mock.AsyncMock(
        return_value=[jira_raw_factory(key='MOS-101')],
    )
    upsert = unittest.mock.AsyncMock()
    setting_get = unittest.mock.AsyncMock(return_value=None)

    monkeypatch.setattr(tasks, '_search_issues', search)
    monkeypatch.setattr(tasks, '_upsert_issue_graph', upsert)
    monkeypatch.setattr(models.Setting, 'get', setting_get)

    desired = await tasks.sync_desired_issues(
        app=app,
        session=session,
        transition_timeout=1,
    )

    assert desired == {'MOS-101'}
    assert search.await_args_list == [
        unittest.mock.call(
            jira_client=app.state.jira_client,
            jql='(assignee = "account-123")',
        ),
    ]
    assert [call.args[0]['key'] for call in upsert.await_args_list] == [
        'MOS-101',
    ]


async def test_sync_desired_issues_limits_transition_sync_after_timeout(
    monkeypatch: pytest.MonkeyPatch,
    jira_raw_factory: IssueFactory,
) -> None:
    app = _build_app()
    session = object()

    search = unittest.mock.AsyncMock(
        return_value=[
            jira_raw_factory(key='MOS-1'),
            jira_raw_factory(key='MOS-2'),
            jira_raw_factory(key='MOS-3'),
        ],
    )
    upsert = unittest.mock.AsyncMock()
    setting_get = unittest.mock.AsyncMock(return_value=None)
    monotonic = unittest.mock.Mock(side_effect=[100.0, 100.0, 100.2, 101.1])

    monkeypatch.setattr(tasks, '_search_issues', search)
    monkeypatch.setattr(tasks, '_upsert_issue_graph', upsert)
    monkeypatch.setattr(models.Setting, 'get', setting_get)
    monkeypatch.setattr(
        tasks,
        'time',
        types.SimpleNamespace(monotonic=monotonic),
    )

    desired = await tasks.sync_desired_issues(
        app=app,
        session=session,
        transition_timeout=1,
    )

    transition_flags = [
        call.kwargs['sync_transitions']
        for call in upsert.await_args_list
    ]
    print('sync_transitions flags:', transition_flags)

    assert desired == {'MOS-1', 'MOS-2', 'MOS-3'}
    assert transition_flags == [True, True, False]


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
