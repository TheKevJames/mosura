import types
import unittest.mock
from collections.abc import Callable
from typing import Any

import httpx
import jira
import pytest

import mosura.app
from mosura import models
from mosura import schemas


async def test_read_issue_success(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    api_session: types.SimpleNamespace,
    issue_factory: Callable[..., schemas.Issue],
) -> None:
    get_mock = unittest.mock.AsyncMock(return_value=[issue_factory('MOS-101')])
    monkeypatch.setattr(models.Issue, 'get', get_mock)

    response = await client.get('/api/v0/issues/MOS-101')
    print('GET success:', response.status_code, response.text)

    assert response.status_code == 200
    assert response.json()['key'] == 'MOS-101'
    get_mock.assert_awaited_once_with(
        key='MOS-101',
        closed=True,
        session=api_session,
    )


async def test_read_issue_not_found(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    api_session: types.SimpleNamespace,
) -> None:
    get_mock = unittest.mock.AsyncMock(return_value=[])
    monkeypatch.setattr(models.Issue, 'get', get_mock)

    response = await client.get('/api/v0/issues/MOS-404')
    print('GET missing:', response.status_code, response.text)

    assert response.status_code == 404
    get_mock.assert_awaited_once_with(
        key='MOS-404',
        closed=True,
        session=api_session,
    )


async def test_patch_issue_not_found(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    api_session: types.SimpleNamespace,
) -> None:
    get_mock = unittest.mock.AsyncMock(return_value=[])
    upsert_mock = unittest.mock.AsyncMock()
    monkeypatch.setattr(models.Issue, 'get', get_mock)
    monkeypatch.setattr(models.Issue, 'upsert', upsert_mock)

    response = await client.patch(
        '/api/v0/issues/MOS-404',
        json={'summary': 'X'},
    )
    print('PATCH missing:', response.status_code, response.text)

    assert response.status_code == 404
    get_mock.assert_awaited_once_with(
        key='MOS-404',
        closed=True,
        session=api_session,
    )
    upsert_mock.assert_not_awaited()
    api_session.commit.assert_not_awaited()


async def test_patch_issue_conflict(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    api_session: types.SimpleNamespace,
    jira_raw_factory: Callable[..., dict[str, Any]],
    issue_from_jira_factory: Callable[..., schemas.Issue],
    jira_issue_factory: Callable[[dict[str, Any]], jira.Issue],
) -> None:
    raw = jira_raw_factory(key='MOS-777', summary='Canonical summary')
    cached_issue = issue_from_jira_factory(
        raw,
        summary='Changed summary locally',
    )

    get_mock = unittest.mock.AsyncMock(return_value=[cached_issue])
    upsert_mock = unittest.mock.AsyncMock()

    live_issue = jira_issue_factory(raw)
    update_mock = unittest.mock.Mock()
    monkeypatch.setattr(
        live_issue,
        'update',
        update_mock,
        raising=False,
    )

    jira_issue = unittest.mock.MagicMock(return_value=live_issue)
    mosura.app.app.state.jira_client = types.SimpleNamespace(issue=jira_issue)

    schedule_refresh_mock = unittest.mock.Mock()
    monkeypatch.setattr(
        'mosura.api.tasks.schedule_issue_refresh',
        schedule_refresh_mock,
    )
    monkeypatch.setattr(models.Issue, 'get', get_mock)
    monkeypatch.setattr(models.Issue, 'upsert', upsert_mock)

    response = await client.patch(
        '/api/v0/issues/MOS-777',
        json={'summary': 'New'},
    )
    print('PATCH conflict:', response.status_code, response.text)

    assert response.status_code == 409
    assert response.json()['detail'] == (
        'This issue was modified in Jira while you were editing it, '
        'please refresh the page and try again.'
    )
    jira_issue.assert_called_once_with(
        id='MOS-777',
        fields=schemas.Issue.jira_fields(),
        expand='renderedFields',
    )
    schedule_refresh_mock.assert_called_once_with(
        app=mosura.app.app,
        key='MOS-777',
    )
    update_mock.assert_not_called()
    upsert_mock.assert_not_awaited()
    api_session.commit.assert_not_awaited()


async def test_patch_issue_success(  # pylint: disable=too-many-locals
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    api_session: types.SimpleNamespace,
    jira_raw_factory: Callable[..., dict[str, Any]],
    issue_from_jira_factory: Callable[..., schemas.Issue],
    jira_issue_factory: Callable[[dict[str, Any]], jira.Issue],
) -> None:
    raw = jira_raw_factory(key='MOS-204', summary='Current summary')
    cached_issue = issue_from_jira_factory(
        raw,
        components=['Platform'],
        labels=['okr'],
    )

    get_mock = unittest.mock.AsyncMock(return_value=[cached_issue])
    upsert_mock = unittest.mock.AsyncMock()

    live_issue = jira_issue_factory(raw)
    update_mock = unittest.mock.Mock()
    monkeypatch.setattr(
        live_issue,
        'update',
        update_mock,
        raising=False,
    )

    jira_issue = unittest.mock.MagicMock(return_value=live_issue)
    mosura.app.app.state.jira_client = types.SimpleNamespace(issue=jira_issue)

    monkeypatch.setattr(models.Issue, 'get', get_mock)
    monkeypatch.setattr(models.Issue, 'upsert', upsert_mock)

    response = await client.patch(
        '/api/v0/issues/MOS-204',
        json={'summary': 'Updated summary', 'priority': 'High'},
    )
    print('PATCH success:', response.status_code, response.text)

    assert response.status_code == 204
    jira_issue.assert_called_once_with(
        id='MOS-204',
        fields=schemas.Issue.jira_fields(),
        expand='renderedFields',
    )
    update_mock.assert_called_once_with(
        fields={
            'summary': 'Updated summary',
            'priority': {'name': 'High'},
        },
    )
    upsert_mock.assert_awaited_once()
    await_args = upsert_mock.await_args
    assert await_args is not None
    assert await_args.kwargs == {'session': api_session}

    updated_issue = await_args.args[0]
    assert isinstance(updated_issue, schemas.Issue)
    assert updated_issue.key == 'MOS-204'
    assert updated_issue.summary == 'Updated summary'
    assert updated_issue.priority == schemas.Priority.high

    api_session.commit.assert_awaited_once()
