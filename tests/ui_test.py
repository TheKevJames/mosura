import types
import unittest.mock

import niquests
import pytest

import mosura.app
from mosura import models
from mosura import ui


@pytest.mark.parametrize(
    ('status', 'color'),
    [
        ('Backlog', ''),
        ('Closed', 'green'),
        ('Code Review', 'yellow'),
        ('Done', 'green'),
        ('In Progress', 'yellow'),
        ('Needs Triage', 'red'),
        ('Ready for Testing', 'yellow'),
        ('Root Caused', 'green'),
        ('To Do', ''),
    ],
)
def test_statuscolor_filter(status: str, color: str) -> None:
    template = ui.templates.env.from_string('{{ status | statuscolor }}')
    assert template.render(status=status) == color


@pytest.mark.usefixtures('api_session')
async def test_base_renders_sync_icon(
    client: niquests.AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        models.Setting, 'get', unittest.mock.AsyncMock(return_value=None)
    )
    monkeypatch.setattr(
        mosura.app.app.state,
        'settings',
        types.SimpleNamespace(
            jira_domain='https://jira.example.com',
            jira_auth_user='auth@example.com',
            jira_tracked_user='alice',
            mosura_poll_interval=60,
        ),
        raising=False,
    )

    response = await client.get('/settings')

    assert response.status_code == 200
    assert response.text is not None
    assert 'id="sync"' in response.text
    assert '<i class="sync icon"></i>' in response.text
    assert 'fetch("/api/v0/sync", {method: "POST"})' in response.text
