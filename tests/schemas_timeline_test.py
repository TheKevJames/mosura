import datetime
from collections.abc import Callable

from mosura import schemas


def test_partition_issues_applies_triage_and_window_rules(
    issue_factory: Callable[..., schemas.Issue],
) -> None:
    start_date = datetime.date(2024, 1, 1)
    end_date = datetime.date(2024, 2, 1)

    issues = [
        issue_factory('TRIAGE-1', assignee='Alice', startdate=None),
        issue_factory(
            'CLOSED-1',
            assignee='Alice',
            status='Closed',
            startdate=None,
        ),
        issue_factory(
            'FUTURE-1',
            assignee='Alice',
            startdate=datetime.date(2024, 2, 5),
        ),
        issue_factory(
            'PAST-1',
            assignee='Alice',
            startdate=datetime.date(2023, 12, 1),
            timeestimate=datetime.timedelta(days=14),
        ),
        issue_factory(
            'ALIGN-1',
            assignee='Alice',
            startdate=datetime.date(2024, 1, 15),
            timeestimate=datetime.timedelta(days=14),
        ),
    ]

    aligning, triage = schemas.Timeline.partition_issues(
        issues,
        start_date,
        end_date,
    )

    assert [issue.key for issue in aligning] == ['ALIGN-1']
    assert [issue.key for issue in triage] == ['TRIAGE-1']


def test_get_boxes_anchors_to_monday_and_flags_visible_weeks() -> None:
    monday, boxes = schemas.Timeline.get_boxes(
        target=datetime.date(2024, 1, 10),
        weeks_before=2,
        weeks_after=1,
    )

    assert monday == datetime.date(2024, 1, 8)
    assert boxes == [
        (datetime.date(2023, 12, 25), False),
        (datetime.date(2024, 1, 1), False),
        (datetime.date(2024, 1, 8), True),
        (datetime.date(2024, 1, 15), True),
    ]


def test_align_issues_packs_rows_and_inserts_gaps(
    issue_factory: Callable[..., schemas.Issue],
) -> None:
    start = datetime.date(2024, 1, 1)
    end = datetime.date(2024, 2, 12)

    issues = [
        issue_factory(
            'A',
            startdate=datetime.date(2024, 1, 1),
            timeestimate=datetime.timedelta(days=14),
        ),
        issue_factory(
            'B',
            startdate=datetime.date(2024, 1, 8),
            timeestimate=datetime.timedelta(days=14),
        ),
        issue_factory(
            'C',
            startdate=datetime.date(2024, 1, 15),
        ),
        issue_factory(
            'D',
            startdate=datetime.date(2024, 1, 29),
        ),
    ]

    aligned = schemas.Timeline.align_issues(issues, start, end)

    assert len(aligned) == 2
    assert [
        (span, issue.key if issue else None)
        for span, issue in aligned[0]
    ] == [
        (2, 'A'),
        (1, 'C'),
        (1, None),
        (1, 'D'),
    ]
    assert [
        (span, issue.key if issue else None)
        for span, issue in aligned[1]
    ] == [
        (1, None),
        (2, 'B'),
    ]


def test_align_issues_clamps_span_to_window(
    issue_factory: Callable[..., schemas.Issue],
) -> None:
    start = datetime.date(2024, 1, 1)
    end = datetime.date(2024, 2, 12)
    issue = issue_factory(
        'CLAMP',
        startdate=datetime.date(2023, 12, 18),
        timeestimate=datetime.timedelta(days=70),
    )

    aligned = schemas.Timeline.align_issues([issue], start, end)

    assert [
        (span, item.key if item else None)
        for span, item in aligned[0]
    ] == [
        (6, 'CLAMP'),
    ]


def test_from_issues_collects_triage_and_aligns(
    issue_factory: Callable[..., schemas.Issue],
) -> None:
    issues = [
        issue_factory(
            'ANN-1',
            assignee='Ann',
            summary='Ann scheduled',
            startdate=datetime.date(2024, 1, 8),
        ),
        issue_factory(
            'ANN-2',
            assignee='Ann',
            summary='Zed triage',
            startdate=None,
        ),
        issue_factory(
            'BOB-1',
            assignee='Bob',
            summary='Bob scheduled',
            startdate=datetime.date(2024, 1, 15),
        ),
    ]

    timeline = schemas.Timeline.from_issues(
        issues,
        target=datetime.date(2024, 1, 10),
        weeks_before=0,
        weeks_after=1,
    )

    assert timeline.monday == datetime.date(2024, 1, 8)
    assert timeline.boxes == [
        (datetime.date(2024, 1, 8), True),
        (datetime.date(2024, 1, 15), True),
    ]

    assert [issue.key for issue in timeline.triage] == ['ANN-2']

    # aligned is now list[list[tuple[int, Issue | None]]]
    # ANN-1 (Jan 8) and BOB-1 (Jan 15) don't overlap, so both fit in row 0
    assert [
        (span, issue.key if issue else None)
        for span, issue in timeline.aligned[0]
    ] == [(1, 'ANN-1'), (1, 'BOB-1')]
