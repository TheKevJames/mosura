import asyncio
import datetime
import unittest.mock
from collections.abc import Awaitable
from collections.abc import Callable
from typing import cast

import fastapi
import pytest

from mosura import tasks


FetchFunc = Callable[
    [fastapi.FastAPI, asyncio.Lock, str, list[str] | None],
    Awaitable[None],
]


@pytest.mark.parametrize(
    ('func_name', 'status_clause', 'interval_seconds', 'variant_suffix'),
    [
        ('fetch_open', 'NOT IN ("Closed", "Done")', 45, 'open'),
        ('fetch_closed', 'IN ("Closed", "Done")', 3600, 'closed'),
    ],
)
@pytest.mark.parametrize(
    ('users', 'assignee_clause'),
    [
        (None, ''),
        (
            ['account-1', 'account-2'],
            ' AND assignee IN ("account-1","account-2")',
        ),
    ],
)
async def test_fetch_builds_expected_jql_variant_and_interval(
    monkeypatch: pytest.MonkeyPatch,
    app_factory: Callable[..., fastapi.FastAPI],
    func_name: str,
    status_clause: str,
    interval_seconds: int,
    variant_suffix: str,
    users: list[str] | None,
    assignee_clause: str,
) -> None:
    app = app_factory(projects=['MOS'])
    lock = asyncio.Lock()
    captured: dict[str, object] = {}

    async def fake_fetch(**kwargs: object) -> None:
        captured.update(kwargs)

    monkeypatch.setattr(tasks, 'fetch', fake_fetch)

    fetch_func = cast(FetchFunc, getattr(tasks, func_name))
    await fetch_func(app, lock, 'MOS', users)

    assert captured == {
        'app': app,
        'interval': datetime.timedelta(seconds=interval_seconds),
        'jql': f'project = "MOS" AND status {status_clause}{assignee_clause}',
        'lock': lock,
        'variant': f'MOS/{variant_suffix}',
    }


async def test_spawn_validates_projects_and_creates_expected_tasks(
    monkeypatch: pytest.MonkeyPatch,
    app_factory: Callable[..., fastapi.FastAPI],
) -> None:
    app = app_factory(projects=['MOS', 'OPS', 'SRE'])
    project_check = cast(unittest.mock.Mock, app.state.jira_client.project)
    users = ['account-1', 'account-2']
    open_calls: list[tuple[str, list[str] | None, asyncio.Lock]] = []
    closed_calls: list[tuple[str, list[str] | None, asyncio.Lock]] = []

    def fake_fetch_open(
        _app: fastapi.FastAPI,
        lock: asyncio.Lock,
        project: str,
        members: list[str] | None = None,
    ) -> object:
        open_calls.append((project, members, lock))
        return ('open', project, members)

    def fake_fetch_closed(
        _app: fastapi.FastAPI,
        lock: asyncio.Lock,
        project: str,
        members: list[str] | None = None,
    ) -> object:
        closed_calls.append((project, members, lock))
        return ('closed', project, members)

    created: list[asyncio.Task[None]] = []

    def fake_create_task(_payload: object, *, name: str) -> asyncio.Task[None]:
        _ = name
        task = cast(
            asyncio.Task[None],
            unittest.mock.Mock(spec=asyncio.Task),
        )
        created.append(task)
        return task

    create_task = unittest.mock.Mock(side_effect=fake_create_task)

    monkeypatch.setattr(tasks, 'fetch_open', fake_fetch_open)
    monkeypatch.setattr(tasks, 'fetch_closed', fake_fetch_closed)
    monkeypatch.setattr(asyncio, 'create_task', create_task)

    spawned = await tasks.spawn(app, users)

    assert project_check.call_args_list == [
        unittest.mock.call('MOS'),
        unittest.mock.call('OPS'),
        unittest.mock.call('SRE'),
    ]
    assert len(spawned) == 6
    assert spawned == set(created)

    assert [item[0] for item in open_calls] == ['MOS', 'OPS', 'SRE']
    assert [item[0] for item in closed_calls] == ['MOS', 'OPS', 'SRE']
    assert open_calls[0][1] is None
    assert closed_calls[0][1] is None
    assert all(call_[1] == users for call_ in open_calls[1:])
    assert all(call_[1] == users for call_ in closed_calls[1:])

    shared_lock = open_calls[0][2]
    assert all(call_[2] is shared_lock for call_ in open_calls + closed_calls)

    assert [
        call.kwargs['name']
        for call in create_task.call_args_list
    ] == [
        'fetch_closed_MOS',
        'fetch_open_MOS',
        'fetch_closed_OPS',
        'fetch_closed_SRE',
        'fetch_open_OPS',
        'fetch_open_SRE',
    ]


async def test_spawn_raises_if_project_validation_fails(
    monkeypatch: pytest.MonkeyPatch,
    app_factory: Callable[..., fastapi.FastAPI],
) -> None:
    def fake_project(project: str) -> object:
        if project == 'BROKEN':
            raise RuntimeError('project lookup failed')
        return object()

    app = app_factory(
        projects=['MOS', 'BROKEN'],
        project_side_effect=fake_project,
    )
    project_check = cast(unittest.mock.Mock, app.state.jira_client.project)

    create_task = unittest.mock.Mock()
    monkeypatch.setattr(asyncio, 'create_task', create_task)

    with pytest.raises(RuntimeError, match='project lookup failed'):
        await tasks.spawn(app, users=['account-1'])

    assert project_check.call_args_list == [
        unittest.mock.call('MOS'),
        unittest.mock.call('BROKEN'),
    ]
    create_task.assert_not_called()
