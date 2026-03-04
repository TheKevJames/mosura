import datetime
from collections.abc import Callable

from mosura import schemas


def test_get_boxes_anchors_to_selected_monday_and_flags_current_week() -> None:
    selected_monday, boxes = schemas.Timeline.get_boxes(
        selected_date=datetime.date(2024, 1, 10),
        current_date=datetime.date(2024, 1, 10),
        weeks_before=2,
        weeks_after=1,
    )

    assert selected_monday == datetime.date(2024, 1, 8)
    assert boxes == [
        (datetime.date(2023, 12, 25), False),
        (datetime.date(2024, 1, 1), False),
        (datetime.date(2024, 1, 8), True),
        (datetime.date(2024, 1, 15), False),
    ]


def test_get_boxes_does_not_highlight_when_current_outside_window() -> None:
    _, boxes = schemas.Timeline.get_boxes(
        selected_date=datetime.date(2024, 1, 10),
        current_date=datetime.date(2024, 3, 1),
        weeks_before=1,
        weeks_after=1,
    )

    assert [is_current for _, is_current in boxes] == [False, False, False]


def test_timeline_range_spans_all_rendered_weeks() -> None:
    timeline = schemas.Timeline.from_issues(
        [],
        selected_date=datetime.date(2026, 3, 2),
        current_date=datetime.date(2026, 3, 2),
    )

    assert timeline.range_start == datetime.date(2026, 2, 9)
    assert timeline.range_end == datetime.date(2026, 4, 13)


def test_timeline_segment_creation() -> None:
    """Test TimelineSegment dataclass."""
    segment = schemas.TimelineSegment(
        start=datetime.date(2024, 1, 1),
        end=datetime.date(2024, 1, 5),
        status='Backlog',
    )
    assert segment.start == datetime.date(2024, 1, 1)
    assert segment.end == datetime.date(2024, 1, 5)
    assert segment.status == 'Backlog'


def test_timeline_issue_creation() -> None:
    """Test TimelineIssue dataclass."""
    segments = [
        schemas.TimelineSegment(
            start=datetime.date(2024, 1, 1),
            end=datetime.date(2024, 1, 5),
            status='Backlog',
        ),
    ]
    issue = schemas.TimelineIssue(
        key='TEST-1',
        summary='Test issue',
        status='Closed',
        created=datetime.date(2024, 1, 1),
        startdate=datetime.date(2024, 1, 2),
        segments=segments,
        estimated_completion=datetime.date(2024, 1, 10),
        overdue=False,
        overdue_start=False,
    )
    assert issue.key == 'TEST-1'
    assert issue.summary == 'Test issue'
    assert issue.status == 'Closed'
    assert issue.created == datetime.date(2024, 1, 1)
    assert issue.startdate == datetime.date(2024, 1, 2)
    assert len(issue.segments) == 1
    assert issue.estimated_completion == datetime.date(2024, 1, 10)
    assert not issue.overdue
    assert not issue.overdue_start


def test_from_issues_single_issue_no_transitions(
    issue_factory: Callable[..., schemas.Issue],
) -> None:
    """Test building timeline with single issue and no transitions."""
    issue = issue_factory(
        'TEST-1',
        summary='Simple issue',
        status='In Progress',
        startdate=datetime.date(2024, 1, 5),
        timeestimate=datetime.timedelta(days=3),
    )

    timeline = schemas.Timeline.from_issues(
        [issue],
        selected_date=datetime.date(2024, 1, 10),
        current_date=datetime.date(2024, 1, 10),
        weeks_before=2,
        weeks_after=2,
    )

    assert len(timeline.issues) == 1
    tli = timeline.issues[0]
    assert tli.key == 'TEST-1'
    assert tli.summary == 'Simple issue'
    assert tli.status == 'In Progress'
    assert tli.segments
    assert tli.estimated_completion == datetime.date(2024, 1, 7)
    assert tli.overdue
    assert not tli.overdue_start


def test_from_issues_builds_segments_from_transitions(
    issue_factory: Callable[..., schemas.Issue],
) -> None:
    """Test that segments are correctly built from status transitions."""
    issue = issue_factory(
        'TEST-2',
        summary='Multi-status issue',
        status='Closed',
        startdate=datetime.date(2024, 1, 1),
        timeestimate=datetime.timedelta(days=10),
    )

    transitions = {
        'TEST-2': [
            schemas.IssueTransition(
                key='TEST-2',
                from_status='Backlog',
                to_status='In Progress',
                timestamp=datetime.datetime(
                    2024, 1, 3, 10, 0, tzinfo=datetime.UTC,
                ),
            ),
            schemas.IssueTransition(
                key='TEST-2',
                from_status='In Progress',
                to_status='Code Review',
                timestamp=datetime.datetime(
                    2024, 1, 8, 10, 0, tzinfo=datetime.UTC,
                ),
            ),
            schemas.IssueTransition(
                key='TEST-2',
                from_status='Code Review',
                to_status='Closed',
                timestamp=datetime.datetime(
                    2024, 1, 10, 10, 0, tzinfo=datetime.UTC,
                ),
            ),
        ],
    }

    timeline = schemas.Timeline.from_issues(
        [issue],
        transitions=transitions,
        selected_date=datetime.date(2024, 1, 10),
        current_date=datetime.date(2024, 1, 10),
        weeks_before=2,
        weeks_after=2,
    )

    assert len(timeline.issues) == 1
    tli = timeline.issues[0]
    assert tli.key == 'TEST-2'
    assert tli.status == 'Closed'
    assert len(tli.segments) == 4


def test_from_issues_day_counting_rule(
    issue_factory: Callable[..., schemas.Issue],
) -> None:
    """
    Test the day-counting rule for estimated_completion.

    The base date counts as day 1.
    estimated_completion = base_date + timedelta(
        days=max(timeestimate.days - 1, 0)
    )
    """
    issue = issue_factory(
        'TEST-3',
        summary='Day count test',
        status='In Progress',
        startdate=datetime.date(2024, 3, 3),
        timeestimate=datetime.timedelta(days=2),
    )

    timeline = schemas.Timeline.from_issues(
        [issue],
        selected_date=datetime.date(2024, 3, 5),
        current_date=datetime.date(2024, 3, 5),
        weeks_before=1,
        weeks_after=1,
    )

    tli = timeline.issues[0]
    assert tli.estimated_completion == datetime.date(2024, 3, 4)


def test_from_issues_day_counting_with_in_progress_transition(
    issue_factory: Callable[..., schemas.Issue],
) -> None:
    issue = issue_factory(
        'TEST-4',
        summary='In progress start date',
        status='In Progress',
        startdate=datetime.date(2024, 1, 1),
        timeestimate=datetime.timedelta(days=5),
    )

    transitions = {
        'TEST-4': [
            schemas.IssueTransition(
                key='TEST-4',
                from_status='Backlog',
                to_status='In Progress',
                timestamp=datetime.datetime(
                    2024, 1, 5, 10, 0, tzinfo=datetime.UTC,
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
        weeks_after=2,
    )

    tli = timeline.issues[0]
    assert tli.estimated_completion == datetime.date(2024, 1, 9)


def test_from_issues_overdue_detection_uses_current_date(
    issue_factory: Callable[..., schemas.Issue],
) -> None:
    current_date = datetime.date(2024, 1, 10)
    issue = issue_factory(
        'TEST-5',
        summary='Overdue issue',
        status='In Progress',
        startdate=datetime.date(2024, 1, 1),
        timeestimate=datetime.timedelta(days=3),  # completion = Jan 3
    )

    timeline = schemas.Timeline.from_issues(
        [issue],
        selected_date=datetime.date(2024, 1, 3),
        current_date=current_date,
        weeks_before=1,
        weeks_after=1,
    )

    tli = timeline.issues[0]
    assert tli.estimated_completion == datetime.date(2024, 1, 3)
    assert tli.overdue


def test_from_issues_no_overdue_when_closed(
    issue_factory: Callable[..., schemas.Issue],
) -> None:
    today = datetime.date(2024, 1, 10)
    issue = issue_factory(
        'TEST-6',
        summary='Closed past due',
        status='Closed',
        startdate=datetime.date(2024, 1, 1),
        timeestimate=datetime.timedelta(days=3),
    )

    transitions = {
        'TEST-6': [
            schemas.IssueTransition(
                key='TEST-6',
                from_status='Backlog',
                to_status='Closed',
                timestamp=datetime.datetime(
                    2024, 1, 4, 10, 0, tzinfo=datetime.UTC,
                ),
            ),
        ],
    }

    timeline = schemas.Timeline.from_issues(
        [issue],
        transitions=transitions,
        selected_date=today,
        current_date=today,
        weeks_before=1,
        weeks_after=1,
    )

    tli = timeline.issues[0]
    assert tli.status == 'Closed'
    assert not tli.overdue


def test_from_issues_overdue_start_detection(
    issue_factory: Callable[..., schemas.Issue],
) -> None:
    today = datetime.date(2024, 1, 10)
    issue = issue_factory(
        'TEST-7',
        summary='Not started',
        status='Backlog',
        startdate=datetime.date(2024, 1, 1),
        timeestimate=datetime.timedelta(days=10),
    )

    timeline = schemas.Timeline.from_issues(
        [issue],
        selected_date=today,
        current_date=today,
        weeks_before=1,
        weeks_after=1,
    )

    tli = timeline.issues[0]
    assert tli.overdue_start


def test_from_issues_no_overdue_start_when_in_progress(
    issue_factory: Callable[..., schemas.Issue],
) -> None:
    """Test overdue_start is False when In Progress transition exists."""
    today = datetime.date(2024, 1, 10)
    issue = issue_factory(
        'TEST-8',
        summary='Started but old',
        status='In Progress',
        startdate=datetime.date(2024, 1, 1),
        timeestimate=datetime.timedelta(days=10),
    )

    transitions = {
        'TEST-8': [
            schemas.IssueTransition(
                key='TEST-8',
                from_status='Backlog',
                to_status='In Progress',
                timestamp=datetime.datetime(
                    2024, 1, 5, 10, 0, tzinfo=datetime.UTC,
                ),
            ),
        ],
    }

    timeline = schemas.Timeline.from_issues(
        [issue],
        transitions=transitions,
        selected_date=today,
        current_date=today,
        weeks_before=1,
        weeks_after=1,
    )

    tli = timeline.issues[0]
    assert not tli.overdue_start


def test_from_issues_clamping_to_view_window(
    issue_factory: Callable[..., schemas.Issue],
) -> None:
    """Test that segments are clamped to the view window."""
    issue = issue_factory(
        'TEST-9',
        summary='Spans beyond view',
        status='In Progress',
        startdate=datetime.date(2023, 12, 15),  # Before view start
        timeestimate=datetime.timedelta(days=90),  # Extends past view end
    )

    timeline = schemas.Timeline.from_issues(
        [issue],
        selected_date=datetime.date(2024, 1, 10),
        current_date=datetime.date(2024, 1, 10),
        weeks_before=2,
        weeks_after=2,
    )

    tli = timeline.issues[0]
    view_start = timeline.selected_monday - datetime.timedelta(days=7 * 2)
    view_end = (
        timeline.selected_monday + datetime.timedelta(days=7 * 3)
    )  # 2 after

    for segment in tli.segments:
        assert segment.start >= view_start
        assert segment.end <= view_end


def test_from_issues_partition_to_attention_list_no_timeestimate(
    issue_factory: Callable[..., schemas.Issue],
) -> None:
    """Test that issues with no timeestimate go to attention list."""
    issue = issue_factory(
        'TEST-10',
        summary='No estimate',
        status='In Progress',
        startdate=datetime.date(2024, 1, 5),
        timeestimate=datetime.timedelta(days=0),  # No estimate
    )

    timeline = schemas.Timeline.from_issues(
        [issue],
        selected_date=datetime.date(2024, 1, 10),
        current_date=datetime.date(2024, 1, 10),
        weeks_before=1,
        weeks_after=1,
    )

    assert len(timeline.attention) == 1
    assert timeline.attention[0].key == 'TEST-10'
    assert not timeline.issues


def test_from_issues_partition_to_attention_list_overdue_start(
    issue_factory: Callable[..., schemas.Issue],
) -> None:
    """Test that overdue_start issues go to attention list."""
    today = datetime.date(2024, 1, 10)
    issue = issue_factory(
        'TEST-11',
        summary='Not started old',
        status='Backlog',
        startdate=datetime.date(2023, 12, 1),  # Past
        timeestimate=datetime.timedelta(days=10),
    )

    timeline = schemas.Timeline.from_issues(
        [issue],
        selected_date=today,
        current_date=today,
        weeks_before=4,
        weeks_after=1,
    )

    assert len(timeline.attention) == 1
    assert timeline.attention[0].key == 'TEST-11'
    found_in_attention = any(i.key == 'TEST-11' for i in timeline.attention)
    assert found_in_attention


def test_from_issues_partition_closed_issues_excluded_from_attention(
    issue_factory: Callable[..., schemas.Issue],
) -> None:
    """Test that closed issues never go to attention list."""
    issue = issue_factory(
        'TEST-12',
        summary='Closed no estimate',
        status='Closed',
        startdate=datetime.date(2024, 1, 1),
        timeestimate=datetime.timedelta(days=0),  # No estimate
    )

    timeline = schemas.Timeline.from_issues(
        [issue],
        selected_date=datetime.date(2024, 1, 10),
        current_date=datetime.date(2024, 1, 10),
        weeks_before=1,
        weeks_after=1,
    )

    assert len([i for i in timeline.attention if i.key == 'TEST-12']) == 0
