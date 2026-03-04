import datetime
import logging
from collections.abc import Callable

import pytest

from mosura import schemas


def test_from_issues_marks_overdue_when_estimate_is_one_day_past(
    issue_factory: Callable[..., schemas.Issue],
) -> None:
    current_date = datetime.date(2024, 1, 10)
    issue = issue_factory(
        'TEST-5A',
        summary='Slightly overdue issue',
        status='In Progress',
        startdate=datetime.date(2024, 1, 8),
        timeestimate=datetime.timedelta(days=2),  # completion = Jan 9
    )

    timeline = schemas.Timeline.from_issues(
        [issue],
        selected_date=current_date,
        current_date=current_date,
        weeks_before=1,
        weeks_after=1,
    )

    tli = timeline.issues[0]
    assert tli.estimated_completion == datetime.date(2024, 1, 9)
    assert tli.overdue


def test_from_issues_does_not_shorten_open_segment_before_current_date(
    issue_factory: Callable[..., schemas.Issue],
    transition_factory: Callable[..., schemas.IssueTransition],
) -> None:
    current_date = datetime.date(2024, 1, 10)
    issue = issue_factory(
        'TEST-5B',
        summary='Ready for testing but overdue',
        status='Ready for Testing',
        startdate=None,
        timeestimate=datetime.timedelta(days=3),
    )

    transitions = {
        'TEST-5B': [
            transition_factory(
                key='TEST-5B',
                from_status='Backlog',
                to_status='In Progress',
                timestamp=datetime.datetime(
                    2024, 1, 5, 10, 0, tzinfo=datetime.UTC,
                ),
            ),
            transition_factory(
                key='TEST-5B',
                from_status='In Progress',
                to_status='Code Review',
                timestamp=datetime.datetime(
                    2024, 1, 8, 10, 0, tzinfo=datetime.UTC,
                ),
            ),
            transition_factory(
                key='TEST-5B',
                from_status='Code Review',
                to_status='Ready for Testing',
                timestamp=datetime.datetime(
                    2024, 1, 9, 10, 0, tzinfo=datetime.UTC,
                ),
            ),
        ],
    }

    timeline = schemas.Timeline.from_issues(
        [issue],
        transitions=transitions,
        selected_date=current_date,
        current_date=current_date,
        weeks_before=1,
        weeks_after=1,
    )

    tli = timeline.issues[0]
    ready_segment = next(
        segment
        for segment in tli.segments
        if segment.status == 'Ready for Testing'
    )
    assert tli.estimated_completion == datetime.date(2024, 1, 7)
    assert tli.overdue
    assert ready_segment.end == current_date


def test_from_issues_logs_inverted_segments(
    caplog: pytest.LogCaptureFixture,
    issue_factory: Callable[..., schemas.Issue],
    transition_factory: Callable[..., schemas.IssueTransition],
) -> None:
    issue = issue_factory(
        'TEST-5C',
        summary='Future transition causes inverted segment',
        status='Ready for Testing',
        startdate=None,
        timeestimate=datetime.timedelta(days=2),
    )

    transitions = {
        'TEST-5C': [
            transition_factory(
                key='TEST-5C',
                from_status='Backlog',
                to_status='In Progress',
                timestamp=datetime.datetime(
                    2024, 1, 5, 10, 0, tzinfo=datetime.UTC,
                ),
            ),
            transition_factory(
                key='TEST-5C',
                from_status='In Progress',
                to_status='Ready for Testing',
                timestamp=datetime.datetime(
                    2024, 1, 12, 10, 0, tzinfo=datetime.UTC,
                ),
            ),
        ],
    }

    with caplog.at_level(logging.ERROR, logger='mosura.schemas.timeline'):
        schemas.Timeline.from_issues(
            [issue],
            transitions=transitions,
            selected_date=datetime.date(2024, 1, 10),
            current_date=datetime.date(2024, 1, 10),
            weeks_before=1,
            weeks_after=1,
        )

    assert 'timeline segment has inverted dates for TEST-5C' in caplog.text
