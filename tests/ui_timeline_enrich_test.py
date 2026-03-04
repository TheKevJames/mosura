import datetime
from collections.abc import Callable

import pytest

from mosura import schemas
from mosura import ui

# pylint: disable=protected-access


def test_enrich_draws_markers_only_for_same_color_off_left_edge(
    issue_factory: Callable[..., schemas.Issue],
    transition_factory: Callable[..., schemas.IssueTransition],
) -> None:
    issue = issue_factory(
        'TEST-MARKERS',
        status='Closed',
        created=datetime.datetime(2023, 12, 29, 9, 0, tzinfo=datetime.UTC),
        updated=datetime.datetime(2024, 1, 7, 9, 0, tzinfo=datetime.UTC),
        timeestimate=datetime.timedelta(days=10),
    )
    transitions = {
        'TEST-MARKERS': [
            transition_factory(
                key='TEST-MARKERS',
                from_status='Backlog',
                to_status='In Progress',
                timestamp=datetime.datetime(
                    2024, 1, 1, 9, 0, tzinfo=datetime.UTC,
                ),
            ),
            transition_factory(
                key='TEST-MARKERS',
                from_status='In Progress',
                to_status='Code Review',
                timestamp=datetime.datetime(
                    2024, 1, 3, 9, 0, tzinfo=datetime.UTC,
                ),
            ),
            transition_factory(
                key='TEST-MARKERS',
                from_status='Code Review',
                to_status='Ready for Testing',
                timestamp=datetime.datetime(
                    2024, 1, 4, 9, 0, tzinfo=datetime.UTC,
                ),
            ),
            transition_factory(
                key='TEST-MARKERS',
                from_status='Ready for Testing',
                to_status='Closed',
                timestamp=datetime.datetime(
                    2024, 1, 6, 9, 0, tzinfo=datetime.UTC,
                ),
            ),
        ],
    }

    timeline = schemas.Timeline.from_issues(
        [issue],
        transitions=transitions,
        selected_date=datetime.date(2024, 1, 8),
        current_date=datetime.date(2024, 1, 8),
        weeks_before=1,
        weeks_after=1,
    )
    ui._enrich_timeline_for_template(
        timeline,
        current_date=datetime.date(2024, 1, 8),
    )

    segments = timeline.issues[0].segments
    markers = {
        segment.status: getattr(segment, 'show_transition_marker')
        for segment in segments
    }

    assert markers['In Progress'] is False
    assert markers['Code Review'] is True
    assert markers['Ready for Testing'] is True
    assert markers['Closed'] is False

    in_progress_segment = next(
        segment for segment in segments
        if segment.status == 'In Progress'
    )
    assert getattr(in_progress_segment, 'left_percent') == 0


def test_enrich_renders_segment_end_date_inclusively(
    issue_factory: Callable[..., schemas.Issue],
) -> None:
    issue = issue_factory(
        'TEST-INCLUSIVE-END',
        status='In Progress',
        startdate=datetime.date(2026, 2, 16),
        created=datetime.datetime(
            2026, 2, 16, 9, 0, tzinfo=datetime.UTC,
        ),
        timeestimate=datetime.timedelta(days=8),
    )

    timeline = schemas.Timeline.from_issues(
        [issue],
        selected_date=datetime.date(2026, 2, 23),
        current_date=datetime.date(2026, 2, 23),
        weeks_before=1,
        weeks_after=1,
    )
    ui._enrich_timeline_for_template(
        timeline,
        current_date=datetime.date(2026, 2, 23),
    )

    segment = timeline.issues[0].segments[0]
    # 3 rendered weeks = 21 days total; Feb 16 -> Feb 23 should include both
    # endpoints (8 days), not stop at the boundary after 7.
    assert getattr(segment, 'width_percent') == pytest.approx(8 / 21 * 100)
