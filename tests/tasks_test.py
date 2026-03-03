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
    custom_jql: str | None = 'project = "MOS"',
) -> fastapi.FastAPI:
    app = fastapi.FastAPI()
    app.state.settings = types.SimpleNamespace(
        mosura_custom_jql=custom_jql,
        mosura_poll_interval=60,
    )
    app.state.tracked_user_id = tracked_user_id
    app.state.jira_client = types.SimpleNamespace()
    return app


def test_desired_issue_queries_with_custom_jql() -> None:
    app = _build_app(custom_jql='status = "Needs Triage"')

    assert tasks.desired_issue_queries(app) == [
        ('assignee', 'assignee = "account-123"'),
        ('custom', 'status = "Needs Triage"'),
    ]


def test_desired_issue_queries_without_custom_jql() -> None:
    app = _build_app(custom_jql=None)

    assert tasks.desired_issue_queries(app) == [
        ('assignee', 'assignee = "account-123"'),
    ]


async def test_sync_desired_issues_unions_and_dedupes(
    monkeypatch: pytest.MonkeyPatch,
    jira_raw_factory: IssueFactory,
) -> None:
    app = _build_app(custom_jql='project = "OPS"')
    session = object()

    assignee_issues = [
        jira_raw_factory(key='MOS-1', summary='assignee 1'),
        jira_raw_factory(key='MOS-2', summary='assignee overlap'),
    ]
    custom_issues = [
        jira_raw_factory(key='MOS-2', summary='custom overlap winner'),
        jira_raw_factory(key='OPS-9', summary='custom 9'),
    ]

    search = unittest.mock.AsyncMock(
        side_effect=[assignee_issues, custom_issues],
    )
    upsert = unittest.mock.AsyncMock()

    monkeypatch.setattr(tasks, '_search_issues', search)
    monkeypatch.setattr(tasks, '_upsert_issue_graph', upsert)

    desired = await tasks.sync_desired_issues(app=app, session=session)

    assert desired == {'MOS-1', 'MOS-2', 'OPS-9'}
    assert search.await_args_list == [
        unittest.mock.call(
            jira_client=app.state.jira_client,
            jql='assignee = "account-123"',
        ),
        unittest.mock.call(
            jira_client=app.state.jira_client,
            jql='project = "OPS"',
        ),
    ]

    keys = [call.args[0]['key'] for call in upsert.await_args_list]
    assert len(keys) == 3
    assert set(keys) == {'MOS-1', 'MOS-2', 'OPS-9'}

    upserted = {
        call.args[0]['key']: call.args[0]
        for call in upsert.await_args_list
    }
    assert upserted['MOS-2']['fields']['summary'] == 'custom overlap winner'
    assert all(
        call.kwargs['session']
        is session for call in upsert.await_args_list
    )


async def test_sync_desired_issues_without_custom_jql(
    monkeypatch: pytest.MonkeyPatch,
    jira_raw_factory: IssueFactory,
) -> None:
    app = _build_app(custom_jql=None)
    session = object()

    search = unittest.mock.AsyncMock(
        return_value=[jira_raw_factory(key='MOS-101')],
    )
    upsert = unittest.mock.AsyncMock()

    monkeypatch.setattr(tasks, '_search_issues', search)
    monkeypatch.setattr(tasks, '_upsert_issue_graph', upsert)

    desired = await tasks.sync_desired_issues(app=app, session=session)

    assert desired == {'MOS-101'}
    assert search.await_args_list == [
        unittest.mock.call(
            jira_client=app.state.jira_client,
            jql='assignee = "account-123"',
        ),
    ]
    assert [call.args[0]['key'] for call in upsert.await_args_list] == [
        'MOS-101',
    ]


async def test_reconcile_stale_issues_final_sync_then_delete(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _build_app()
    session = object()

    list_keys = unittest.mock.AsyncMock(
        return_value=['OPS-9', 'MOS-2', 'MOS-1'],
    )
    final_fetch = unittest.mock.AsyncMock(
        side_effect=[
            {'key': 'MOS-1'},
            {'key': 'OPS-9'},
        ],
    )
    upsert = unittest.mock.AsyncMock()
    hard_delete = unittest.mock.AsyncMock()

    monkeypatch.setattr(models.Issue, 'list_keys', list_keys)
    monkeypatch.setattr(tasks, '_fetch_issue_by_key', final_fetch)
    monkeypatch.setattr(tasks, '_upsert_issue_graph', upsert)
    monkeypatch.setattr(models.Issue, 'hard_delete', hard_delete)

    stale = await tasks.reconcile_stale_issues(
        app=app,
        session=session,
        desired_keys={'MOS-2'},
        timeout_seconds=30,
    )

    assert stale == {'MOS-1', 'OPS-9'}
    assert [call.kwargs['key'] for call in final_fetch.await_args_list] == [
        'MOS-1',
        'OPS-9',
    ]
    assert [call.args[0]['key'] for call in upsert.await_args_list] == [
        'MOS-1',
        'OPS-9',
    ]
    assert hard_delete.await_args_list == [
        unittest.mock.call('MOS-1', session=session),
        unittest.mock.call('OPS-9', session=session),
    ]


async def test_reconcile_stale_issues_deletes_on_final_fetch_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _build_app()
    session = object()

    list_keys = unittest.mock.AsyncMock(return_value=['MOS-404'])
    final_fetch = unittest.mock.AsyncMock(return_value=None)
    upsert = unittest.mock.AsyncMock()
    hard_delete = unittest.mock.AsyncMock()

    monkeypatch.setattr(models.Issue, 'list_keys', list_keys)
    monkeypatch.setattr(tasks, '_fetch_issue_by_key', final_fetch)
    monkeypatch.setattr(tasks, '_upsert_issue_graph', upsert)
    monkeypatch.setattr(models.Issue, 'hard_delete', hard_delete)

    stale = await tasks.reconcile_stale_issues(
        app=app,
        session=session,
        desired_keys=set(),
        timeout_seconds=30,
    )

    assert stale == {'MOS-404'}
    upsert.assert_not_awaited()
    hard_delete.assert_awaited_once_with('MOS-404', session=session)


async def test_reconcile_stale_issues_keeps_custom_jql_matches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _build_app(custom_jql='project = "OPS"')
    session = object()

    list_keys = unittest.mock.AsyncMock(return_value=['MOS-1', 'OPS-9'])
    final_fetch = unittest.mock.AsyncMock(return_value={'key': 'MOS-1'})
    upsert = unittest.mock.AsyncMock()
    hard_delete = unittest.mock.AsyncMock()

    monkeypatch.setattr(models.Issue, 'list_keys', list_keys)
    monkeypatch.setattr(tasks, '_fetch_issue_by_key', final_fetch)
    monkeypatch.setattr(tasks, '_upsert_issue_graph', upsert)
    monkeypatch.setattr(models.Issue, 'hard_delete', hard_delete)

    stale = await tasks.reconcile_stale_issues(
        app=app,
        session=session,
        desired_keys={'OPS-9'},
        timeout_seconds=30,
    )

    assert stale == {'MOS-1'}
    final_fetch.assert_awaited_once_with(
        jira_client=app.state.jira_client,
        key='MOS-1',
    )
    hard_delete.assert_awaited_once_with('MOS-1', session=session)


async def test_reconcile_stale_issues_stops_after_timeout_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _build_app()
    session = object()

    list_keys = unittest.mock.AsyncMock(return_value=['MOS-1', 'MOS-2'])
    final_fetch = unittest.mock.AsyncMock(
        side_effect=[
            {'key': 'MOS-1'},
            {'key': 'MOS-2'},
        ],
    )
    upsert = unittest.mock.AsyncMock()
    hard_delete = unittest.mock.AsyncMock()
    monotonic = unittest.mock.Mock(side_effect=[100.0, 100.0, 101.1])

    monkeypatch.setattr(models.Issue, 'list_keys', list_keys)
    monkeypatch.setattr(tasks, '_fetch_issue_by_key', final_fetch)
    monkeypatch.setattr(tasks, '_upsert_issue_graph', upsert)
    monkeypatch.setattr(models.Issue, 'hard_delete', hard_delete)
    monkeypatch.setattr(
        tasks,
        'time',
        types.SimpleNamespace(monotonic=monotonic),
    )

    stale = await tasks.reconcile_stale_issues(
        app=app,
        session=session,
        desired_keys=set(),
        timeout_seconds=1,
    )

    assert stale == {'MOS-1'}
    assert [call.kwargs['key'] for call in final_fetch.await_args_list] == [
        'MOS-1',
    ]
    hard_delete.assert_awaited_once_with('MOS-1', session=session)


async def test_spawn_creates_single_desired_worker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _build_app()
    app.state.jira_client.project = unittest.mock.Mock()

    fetched: list[tuple[fastapi.FastAPI, asyncio.Lock]] = []

    def fake_fetch_desired(
        app_: fastapi.FastAPI,
        lock: asyncio.Lock,
    ) -> object:
        fetched.append((app_, lock))
        return ('desired', lock)

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
    assert fetched[0][0] is app
    assert isinstance(fetched[0][1], asyncio.Lock)
    app.state.jira_client.project.assert_not_called()
