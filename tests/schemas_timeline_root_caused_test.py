import datetime
from collections.abc import Callable

from mosura import schemas


def test_from_issues_treats_root_caused_as_closed_for_end_dates(
    issue_factory: Callable[..., schemas.Issue],
) -> None:
    issue = issue_factory(
        'TEST-RC-1',
        summary='Root caused issue',
        status='Root Caused',
        startdate=datetime.date(2024, 1, 1),
        timeestimate=datetime.timedelta(days=5),
    )

    transitions = {
        'TEST-RC-1': [
            schemas.IssueTransition(
                key='TEST-RC-1',
                from_status='In Progress',
                to_status='Root Caused',
                timestamp=datetime.datetime(
                    2024, 1, 8, 12, 0, tzinfo=datetime.UTC,
                ),
            ),
        ],
    }

    timeline = schemas.Timeline.from_issues(
        [issue],
        transitions=transitions,
        selected_date=datetime.date(2024, 1, 10),
        current_date=datetime.date(2024, 1, 10),
        weeks_before=1,
        weeks_after=1,
    )

    tli = timeline.issues[0]
    assert tli.status == 'Closed'
    assert tli.segments[-1].status == 'Root Caused'
    assert tli.segments[-1].end == datetime.date(2024, 1, 8)
    assert not tli.overdue
