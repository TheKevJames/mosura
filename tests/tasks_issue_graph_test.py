import asyncio
import types
import unittest.mock
from collections.abc import Callable
from typing import Any

import pytest

from mosura import models
from mosura import schemas
from mosura import tasks


IssueFactory = Callable[..., dict[str, Any]]


async def _to_thread_inline(
    func: Callable[..., Any],
    *args: Any,
    **kwargs: Any,
) -> Any:
    result = func(*args, **kwargs)
    if asyncio.iscoroutine(result):
        return await result
    return result


async def _upsert_issue_graph(
    issue: dict[str, Any],
    *,
    session: Any,
    tracked_user_name: str,
    jira_client: Any,
) -> None:
    upsert = getattr(tasks, '_upsert_issue_graph')
    app = types.SimpleNamespace(
        state=types.SimpleNamespace(
            tracked_user_name=tracked_user_name,
            jira_client=jira_client,
        ),
    )
    await upsert(
        issue,
        app=app,
        session=session,
    )


async def test_upsert_issue_graph_syncs_transitions_for_tracked_user(
    monkeypatch: pytest.MonkeyPatch,
    jira_raw_factory: IssueFactory,
    api_session: types.SimpleNamespace,
) -> None:
    session = api_session
    issue = jira_raw_factory(
        key='MOS-1',
        assignee='Alice',
        created='2026-01-01T00:00:00.000+0000',
        updated='2026-01-05T10:00:00.000+0000',
    )

    monkeypatch.setattr(
        models.Issue,
        'get',
        unittest.mock.AsyncMock(
            return_value=[
                types.SimpleNamespace(
                    key='MOS-1',
                    transitions_synced_at=None,
                ),
            ],
        ),
    )
    monkeypatch.setattr(models.Issue, 'upsert', unittest.mock.AsyncMock())
    monkeypatch.setattr(
        models.Component,
        'list_',
        unittest.mock.AsyncMock(return_value=set()),
    )
    monkeypatch.setattr(
        models.Component,
        'delete_many',
        unittest.mock.AsyncMock(),
    )
    monkeypatch.setattr(models.Component, 'upsert', unittest.mock.AsyncMock())
    monkeypatch.setattr(
        models.Label,
        'list_',
        unittest.mock.AsyncMock(return_value=set()),
    )
    monkeypatch.setattr(
        models.Label,
        'delete_many',
        unittest.mock.AsyncMock(),
    )
    monkeypatch.setattr(models.Label, 'upsert', unittest.mock.AsyncMock())

    transition_delete = unittest.mock.AsyncMock()
    transition_upsert = unittest.mock.AsyncMock()
    monkeypatch.setattr(models.IssueTransition, 'delete', transition_delete)
    monkeypatch.setattr(models.IssueTransition, 'upsert', transition_upsert)

    session.execute = unittest.mock.AsyncMock()
    jira_client = types.SimpleNamespace(
        issue=unittest.mock.AsyncMock(
            return_value=types.SimpleNamespace(
                raw={
                    'changelog': {
                        'histories': [
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
                        ],
                    },
                },
            ),
        ),
    )
    monkeypatch.setattr('asyncio.to_thread', _to_thread_inline)

    await _upsert_issue_graph(
        issue,
        session=session,
        tracked_user_name='Alice',
        jira_client=jira_client,
    )

    transition_delete.assert_awaited_once_with('MOS-1', session=session)
    assert transition_upsert.await_count == 1


async def test_upsert_issue_graph_skips_transitions_for_non_tracked_user(
    monkeypatch: pytest.MonkeyPatch,
    jira_raw_factory: IssueFactory,
) -> None:
    issue = jira_raw_factory(
        key='MOS-1',
        assignee='Bob',
    )

    monkeypatch.setattr(
        models.Component,
        'list_',
        unittest.mock.AsyncMock(return_value=set()),
    )
    monkeypatch.setattr(
        models.Component,
        'delete_many',
        unittest.mock.AsyncMock(),
    )
    monkeypatch.setattr(models.Component, 'upsert', unittest.mock.AsyncMock())
    monkeypatch.setattr(
        models.Label,
        'list_',
        unittest.mock.AsyncMock(return_value=set()),
    )
    monkeypatch.setattr(
        models.Label,
        'delete_many',
        unittest.mock.AsyncMock(),
    )
    monkeypatch.setattr(models.Label, 'upsert', unittest.mock.AsyncMock())
    monkeypatch.setattr(models.Issue, 'upsert', unittest.mock.AsyncMock())
    transition_delete = unittest.mock.AsyncMock()
    monkeypatch.setattr(models.IssueTransition, 'delete', transition_delete)

    await _upsert_issue_graph(
        issue,
        session=object(),
        tracked_user_name='Alice',
        jira_client=types.SimpleNamespace(),
    )

    transition_delete.assert_not_awaited()


async def test_upsert_issue_graph_only_mutates_changed_components_and_labels(
    monkeypatch: pytest.MonkeyPatch,
    jira_raw_factory: IssueFactory,
) -> None:
    issue = jira_raw_factory(
        key='MOS-9',
        assignee='Bob',
        components=['A', 'B'],
        labels=['x'],
    )

    component_delete_many = unittest.mock.AsyncMock()
    component_upsert = unittest.mock.AsyncMock()
    label_delete_many = unittest.mock.AsyncMock()
    label_upsert = unittest.mock.AsyncMock()

    monkeypatch.setattr(models.Issue, 'upsert', unittest.mock.AsyncMock())
    monkeypatch.setattr(
        models.Component,
        'list_',
        unittest.mock.AsyncMock(return_value={'A', 'C'}),
    )
    monkeypatch.setattr(models.Component, 'delete_many', component_delete_many)
    monkeypatch.setattr(models.Component, 'upsert', component_upsert)
    monkeypatch.setattr(
        models.Label,
        'list_',
        unittest.mock.AsyncMock(return_value={'x', 'y'}),
    )
    monkeypatch.setattr(models.Label, 'delete_many', label_delete_many)
    monkeypatch.setattr(models.Label, 'upsert', label_upsert)

    await _upsert_issue_graph(
        issue,
        session=object(),
        tracked_user_name='Alice',
        jira_client=types.SimpleNamespace(),
    )

    component_delete_many.assert_awaited_once_with(
        'MOS-9',
        {'C'},
        session=unittest.mock.ANY,
    )
    component_upsert.assert_awaited_once()
    component_upsert_call = component_upsert.await_args
    assert component_upsert_call is not None
    assert component_upsert_call.args[0] == schemas.Component(
        key='MOS-9',
        component='B',
    )
    label_delete_many.assert_awaited_once_with(
        'MOS-9',
        {'y'},
        session=unittest.mock.ANY,
    )
    label_upsert.assert_not_awaited()


async def test_upsert_issue_graph_syncs_transitions_for_closed_issue(
    monkeypatch: pytest.MonkeyPatch,
    jira_raw_factory: IssueFactory,
    api_session: types.SimpleNamespace,
) -> None:
    session = api_session
    issue = jira_raw_factory(
        key='MOS-2',
        status='Done',
        assignee='Alice',
        created='2026-01-01T00:00:00.000+0000',
        updated='2026-01-05T10:00:00.000+0000',
    )

    async def get_issue(
        *,
        key: str | None = None,
        closed: bool = False,
        session: Any,
    ) -> list[types.SimpleNamespace]:
        _ = session
        if key == 'MOS-2' and closed:
            return [
                types.SimpleNamespace(
                    key='MOS-2',
                    transitions_synced_at=None,
                ),
            ]
        return []

    issue_get = unittest.mock.AsyncMock(side_effect=get_issue)
    monkeypatch.setattr(models.Issue, 'get', issue_get)
    monkeypatch.setattr(models.Issue, 'upsert', unittest.mock.AsyncMock())
    monkeypatch.setattr(
        models.Component,
        'list_',
        unittest.mock.AsyncMock(return_value=set()),
    )
    monkeypatch.setattr(
        models.Component,
        'delete_many',
        unittest.mock.AsyncMock(),
    )
    monkeypatch.setattr(models.Component, 'upsert', unittest.mock.AsyncMock())
    monkeypatch.setattr(
        models.Label,
        'list_',
        unittest.mock.AsyncMock(return_value=set()),
    )
    monkeypatch.setattr(
        models.Label,
        'delete_many',
        unittest.mock.AsyncMock(),
    )
    monkeypatch.setattr(models.Label, 'upsert', unittest.mock.AsyncMock())

    transition_delete = unittest.mock.AsyncMock()
    transition_upsert = unittest.mock.AsyncMock()
    monkeypatch.setattr(models.IssueTransition, 'delete', transition_delete)
    monkeypatch.setattr(models.IssueTransition, 'upsert', transition_upsert)

    session.execute = unittest.mock.AsyncMock()
    jira_client = types.SimpleNamespace(
        issue=unittest.mock.AsyncMock(
            return_value=types.SimpleNamespace(
                raw={
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
            ),
        ),
    )
    monkeypatch.setattr('asyncio.to_thread', _to_thread_inline)

    await _upsert_issue_graph(
        issue,
        session=session,
        tracked_user_name='Alice',
        jira_client=jira_client,
    )

    print('Issue.get await calls:', issue_get.await_args_list)
    issue_get.assert_awaited_once_with(
        key='MOS-2',
        closed=True,
        session=session,
    )
    transition_delete.assert_awaited_once_with('MOS-2', session=session)
    assert transition_upsert.await_count == 1


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
