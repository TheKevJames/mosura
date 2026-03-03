import datetime
import logging
from collections.abc import Callable
from typing import Any

import pytest

from mosura import schemas


@pytest.mark.parametrize(
    ('jira_status', 'expected_status'),
    [
        ('To Do', 'Backlog'),
        ('Done', 'Closed'),
        ('In Progress', 'In Progress'),
    ],
)
def test_issuecreate_from_jira_normalizes_status(
    jira_status: str,
    expected_status: str,
    jira_raw_factory: Callable[..., dict[str, Any]],
) -> None:
    raw = jira_raw_factory(status=jira_status)

    issue = schemas.IssueCreate.from_jira(raw)

    assert issue.key == 'MOS-123'
    assert issue.summary == 'Ship schema tests'
    assert issue.description == '<p>Rendered description</p>'
    assert issue.assignee == 'Test User'
    assert issue.priority == schemas.Priority.high
    assert issue.votes == 7
    assert issue.status == expected_status
    assert issue.startdate == datetime.date(2026, 1, 5)
    assert issue.timeestimate == datetime.timedelta(days=14)
    assert issue.enddate == datetime.date(2026, 1, 19)


def test_issuecreate_from_jira_uses_timeestimate_when_due_date_is_missing(
    jira_raw_factory: Callable[..., dict[str, Any]],
) -> None:
    raw = jira_raw_factory(
        status='Done',
        calendar_start=None,
        issue_start='2026-01-08',
        due_date=None,
        time_original_estimate='136800',
        assignee=None,
    )

    issue = schemas.IssueCreate.from_jira(raw)

    assert issue.status == 'Closed'
    assert issue.assignee is None
    assert issue.startdate == datetime.date(2026, 1, 8)
    assert issue.timeestimate == datetime.timedelta(days=4, hours=6)
    assert issue.enddate == datetime.date(2026, 1, 12)


def test_issuepatch_to_jira_wraps_priority_name() -> None:
    patch = schemas.IssuePatch(
        priority=schemas.Priority.high,
        summary='Re-run schema mapping',
    )

    assert patch.to_jira() == {
        'priority': {'name': 'High'},
        'summary': 'Re-run schema mapping',
    }


def test_issuepatch_to_jira_omits_unset_fields() -> None:
    assert not schemas.IssuePatch().to_jira()


def test_issue_equality_accepts_matching_jira_issue(
    jira_raw_factory: Callable[..., dict[str, Any]],
    issue_from_jira_factory: Callable[..., schemas.Issue],
    jira_issue_factory: Callable[[dict[str, Any]], Any],
) -> None:
    raw = jira_raw_factory(status='To Do')
    issue = issue_from_jira_factory(raw)
    jira_issue = jira_issue_factory(raw)

    assert issue == jira_issue


def test_issue_equality_logs_mismatch_for_jira_issue(
    caplog: pytest.LogCaptureFixture,
    jira_raw_factory: Callable[..., dict[str, Any]],
    issue_from_jira_factory: Callable[..., schemas.Issue],
    jira_issue_factory: Callable[[dict[str, Any]], Any],
) -> None:
    raw = jira_raw_factory(summary='Canonical summary')
    issue = issue_from_jira_factory(raw, summary='Changed summary locally')
    jira_issue = jira_issue_factory(raw)

    with caplog.at_level(logging.ERROR, logger='mosura.schemas'):
        assert (issue == jira_issue) is False

    assert 'attempted update on out-of-sync issue MOS-123' in caplog.text
    assert (
        'summary: Changed summary locally != Canonical summary'
        in caplog.text
    )
