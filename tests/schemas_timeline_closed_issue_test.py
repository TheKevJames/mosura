import datetime
from collections.abc import Callable

from mosura import schemas


def test_from_issues_closed_without_transitions_uses_updated_date(
    issue_factory: Callable[..., schemas.Issue],
) -> None:
    issue = issue_factory(
        'TEST-6A',
        summary='Closed issue without transitions',
        status='Closed',
        created=datetime.datetime(2018, 4, 19, 18, 31, tzinfo=datetime.UTC),
        updated=datetime.datetime(2018, 4, 30, 7, 30, tzinfo=datetime.UTC),
        timeestimate=datetime.timedelta(days=0),
    )

    timeline = schemas.Timeline.from_issues(
        [issue],
        transitions={},
        selected_date=datetime.date(2018, 5, 1),
        current_date=datetime.date(2018, 5, 1),
        weeks_before=3,
        weeks_after=3,
    )

    tli = timeline.issues[0]
    segment = tli.segments[-1]
    print('closed segment bounds:', segment.start, segment.end)

    assert segment.end == datetime.date(2018, 4, 30)
