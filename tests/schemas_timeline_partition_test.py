import datetime
from collections.abc import Callable

from mosura import schemas


def test_from_issues_mixed_issues(
    issue_factory: Callable[..., schemas.Issue],
) -> None:
    issues = [
        issue_factory(
            'SCHED-1',
            summary='Scheduled',
            status='In Progress',
            startdate=datetime.date(2024, 1, 5),
            timeestimate=datetime.timedelta(days=5),
        ),
        issue_factory(
            'ATTN-1',
            summary='No estimate',
            status='In Progress',
            startdate=datetime.date(2024, 1, 8),
            timeestimate=datetime.timedelta(days=0),
        ),
        issue_factory(
            'CLOSED-1',
            summary='Already done',
            status='Closed',
            startdate=datetime.date(2024, 1, 1),
            timeestimate=datetime.timedelta(days=3),
        ),
    ]

    timeline = schemas.Timeline.from_issues(
        issues,
        selected_date=datetime.date(2024, 1, 10),
        current_date=datetime.date(2024, 1, 10),
        weeks_before=1,
        weeks_after=2,
    )

    timeline_keys = {i.key for i in timeline.issues}
    assert 'SCHED-1' in timeline_keys

    attention_keys = {i.key for i in timeline.attention}
    assert 'ATTN-1' in attention_keys
