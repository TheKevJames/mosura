import datetime
import logging
from collections.abc import Iterator
from typing import Self

import pydantic

from mosura.schemas.issue import Issue
from mosura.schemas.issue import IssueCreate
from mosura.schemas.issue import IssueTransition
from mosura.schemas.issue import Status


logger = logging.getLogger(__name__)


@pydantic.dataclasses.dataclass
class TimelineSegment:
    """
    A contiguous period with a single status.

    Fields:
        start: Start date of the segment
        end: End date of the segment
        status: Status during this segment
    """

    start: datetime.date
    end: datetime.date
    status: str

    # rendering
    left_percent: float = 0.
    width_percent: float | None = None
    show_transition_marker: bool = False

    @pydantic.model_validator(mode='after')
    def log_inverted_segments(self) -> 'TimelineSegment':
        if self.start > self.end:
            logger.error(
                'timeline segment has inverted dates for %s: %s > %s',
                self.status, self.start, self.end,
            )
        return self

    @property
    def status_css_class(self) -> str:
        return f'status-{Status.normalize_status(self.status)}'

    def calculate_rendering(
            self,
            previous: Self | None,
            total_days: int,
            view_start: datetime.date,
    ) -> None:
        segment_start_offset = (self.start - view_start).days
        # Render segment end date inclusively so a segment ending on a
        # given date still fills that date on the chart.
        segment_width = (self.end - self.start).days + 1
        self.left_percent = segment_start_offset / total_days * 100
        self.width_percent = max(
            segment_width / total_days * 100,
            0.1,
        )

        self.show_transition_marker = bool(
            previous
            and previous.status_css_class == self.status_css_class
            and self.left_percent > 0,
        )


@pydantic.dataclasses.dataclass
class TimelineIssue:
    """
    An issue rendered on the timeline with colored status segments.

    Fields:
        key: Issue key
        summary: Issue summary
        status: Current status
        created: Issue creation date
        startdate: Issue scheduled start date
        segments: Status timeline segments
        estimated_completion: Estimated completion date
        overdue: True if past estimated completion and not closed
        overdue_start: True if start date is past and not in progress
    """

    # pylint: disable=too-many-instance-attributes
    key: str
    summary: str
    status: str
    created: datetime.date
    startdate: datetime.date | None
    segments: list[TimelineSegment]
    estimated_completion: datetime.date | None
    overdue: bool
    overdue_start: bool

    # rendering
    estimated_completion_percent: float = 0.
    overdue_start_width_percent: float = 0.
    overdue_width_percent: float = 0.
    startdate_percent: float = 0.

    def calculate_rendering(
            self,
            total_days: int,
            view_start: datetime.date,
            current_date: datetime.date,
    ) -> None:
        if self.estimated_completion:
            days_from_start = (self.estimated_completion - view_start).days
            self.estimated_completion_percent = (
                days_from_start / total_days * 100
            )

        if self.overdue and self.estimated_completion:
            days_overdue = (current_date - self.estimated_completion).days
            self.overdue_width_percent = (
                days_overdue / total_days * 100
            )

        if self.overdue_start and self.startdate:
            days_not_started = (current_date - self.startdate).days
            self.overdue_start_width_percent = (
                days_not_started / total_days * 100
            )

        if self.startdate:
            days_from_start = (self.startdate - view_start).days
            self.startdate_percent = days_from_start / total_days * 100


@pydantic.dataclasses.dataclass
class Timeline:
    issues: list[TimelineIssue]
    attention: list[Issue]
    selected_monday: datetime.date
    boxes: list[tuple[datetime.date, bool]]

    @classmethod
    def from_issues(
            cls,
            issues: list[Issue],
            *,
            selected_date: datetime.date,
            current_date: datetime.date,
            transitions: dict[str, list[IssueTransition]] | None = None,
            weeks_before: int = 3,
            weeks_after: int = 5,
    ) -> 'Timeline':
        """
        Build a timeline from issues and their status transitions.

        Render issues on a timeline with segments for each status period.

        Args:
            issues: List of issues to render
            transitions: Dict mapping issue key to list of transitions
            selected_date: Date to anchor the selected viewport week
            current_date: Real current UTC date for highlight/overdue logic
            weeks_before: Number of weeks before the selected week
            weeks_after: Number of weeks after the selected week
        """
        transitions = transitions or {}
        selected_monday, boxes = cls.get_boxes(
            selected_date=selected_date,
            current_date=current_date,
            weeks_before=weeks_before,
            weeks_after=weeks_after,
        )
        view_start = boxes[0][0]
        view_end = boxes[-1][0] + datetime.timedelta(days=7)

        # Partition issues into timeline and attention
        timeline_issues: list[TimelineIssue] = []
        attention_issues: list[Issue] = []

        for issue in issues:
            # Determine if issue should be in attention list
            if cls._should_attend(
                issue,
                transitions.get(issue.key, []),
                current_date,
                view_start=view_start,
            ):
                attention_issues.append(issue)
                continue

            # Build timeline issue from transitions
            tli = cls._build_timeline_issue(
                issue,
                transitions.get(issue.key, []),
                current_date,
                view_start,
                view_end,
            )
            if tli:
                timeline_issues.append(tli)

        return cls(
            sorted(timeline_issues, key=lambda x: x.created),
            sorted(attention_issues, key=lambda x: x.summary),
            selected_monday,
            boxes,
        )

    @classmethod
    def _should_attend(
            cls,
            issue: Issue,
            trans: list[IssueTransition],
            current_date: datetime.date,
            view_start: datetime.date,
    ) -> bool:
        """
        Determine if an issue should be in the attention list.

        Issues go to attention if:
        - They have no timeestimate (zero timedelta)
        - OR they have overdue_start AND startdate < view_start
        """
        if Status.normalize_status(issue.status) == 'closed':
            return False

        # No timeestimate: needs attention
        if issue.timeestimate == datetime.timedelta(0):
            return True

        # Overdue for starting work
        if cls._overdue_start(issue, trans, current_date):
            # Only put in attention if startdate is before the view window,
            # since otherwise it's already visible in the timeline.
            if issue.startdate and issue.startdate < view_start:
                return True

        return False

    @staticmethod
    def _overdue_start(
            issue: Issue,
            trans: list[IssueTransition],
            current_date: datetime.date,
    ) -> bool:
        # An issue is overdue for having started work if it has an estimated
        # start date in the past, but has not yet transitioned through a
        # working state.
        has_started = any(
            Status.normalize_status(s) == 'in-progress'
            for s in [t.to_status for t in trans] + [issue.status]
        )
        return bool(
            issue.startdate
            and issue.startdate < current_date
            and not has_started
            and Status.normalize_status(issue.status) != 'closed',
        )

    @classmethod
    def _build_timeline_issue_segments(
            cls,
            issue: Issue,
            trans: list[IssueTransition],
            current_date: datetime.date,
    ) -> Iterator[TimelineSegment]:
        """Build timeline segments for an issue from status transitions."""
        created_date = issue.created.date()

        if not trans:
            # TODO: consider scheduling a fetch here
            segment_end = cls._compute_estimated_completion(issue, trans)
            if Status.normalize_status(issue.status) == 'closed':
                segment_end = segment_end or issue.updated.date()
            else:
                segment_end = segment_end or current_date

            yield TimelineSegment(
                start=created_date,
                end=segment_end,
                status=issue.status,
            )
            return

        first_trans = trans[0]
        initial_status = first_trans.from_status or issue.status
        yield TimelineSegment(
            start=created_date,
            end=first_trans.timestamp.date(),
            status=initial_status,
        )

        for i, transition in enumerate(trans[:-1]):
            yield TimelineSegment(
                start=transition.timestamp.date(),
                end=trans[i + 1].timestamp.date(),
                status=transition.to_status,
            )

        last_trans = trans[-1]
        if Status.normalize_status(last_trans.to_status) == 'closed':
            segment_end = last_trans.timestamp.date()
        else:
            est_complete = cls._compute_estimated_completion(issue, trans)
            segment_end = max(est_complete or current_date, current_date)

        yield TimelineSegment(
            start=last_trans.timestamp.date(),
            end=segment_end,
            status=last_trans.to_status,
        )

    @classmethod
    def _build_timeline_issue(
            cls,
            issue: Issue,
            trans: list[IssueTransition],
            current_date: datetime.date,
            view_start: datetime.date,
            view_end: datetime.date,
    ) -> TimelineIssue | None:
        """Build a TimelineIssue from an issue and its transitions."""
        issue_status = IssueCreate.parse_status(issue.status)
        segments = cls._build_timeline_issue_segments(
            issue, trans, current_date,
        )

        clamped_segments: list[TimelineSegment] = []
        view_end_inclusive = view_end - datetime.timedelta(days=1)
        for segment in segments:
            segment.start = max(segment.start, view_start)
            segment.end = min(segment.end, view_end_inclusive)
            if segment.start <= segment.end:
                clamped_segments.append(segment)
        if not clamped_segments:
            return None

        est_completion = cls._compute_estimated_completion(issue, trans)
        overdue = bool(
            est_completion
            and est_completion < current_date
            and Status.normalize_status(issue.status) != 'closed',
        )

        return TimelineIssue(
            key=issue.key,
            summary=issue.summary,
            status=issue_status,
            created=issue.created.date(),
            startdate=issue.startdate,
            segments=clamped_segments,
            estimated_completion=est_completion,
            overdue=overdue,
            overdue_start=cls._overdue_start(issue, trans, current_date),
        )

    @staticmethod
    def _compute_estimated_completion(
            issue: Issue,
            trans: list[IssueTransition],
    ) -> datetime.date | None:
        """Compute estimated completion date for an issue."""
        if Status.normalize_status(issue.status) == 'closed':
            # Closed issues: find close transition date
            return next(
                (
                    t.timestamp.date() for t in trans
                    if Status.normalize_status(t.to_status) == 'closed'
                ),
                None,
            )

        # Look for first in-progress transition
        in_prog_trans = next(
            (
                t for t in trans
                if Status.normalize_status(t.to_status) == 'in-progress'
            ),
            None,
        )
        if in_prog_trans and issue.timeestimate:
            base_date = in_prog_trans.timestamp.date()
            days = max(issue.timeestimate.days - 1, 0)
            return base_date + datetime.timedelta(days=days)

        # No in-progress, use startdate if available
        if issue.startdate and issue.timeestimate:
            days = max(issue.timeestimate.days - 1, 0)
            return issue.startdate + datetime.timedelta(days=days)

        return None

    @staticmethod
    def get_boxes(
            selected_date: datetime.date,
            current_date: datetime.date,
            weeks_before: int,
            weeks_after: int,
    ) -> tuple[datetime.date, list[tuple[datetime.date, bool]]]:
        selected_monday = selected_date - datetime.timedelta(
            days=selected_date.weekday(),
        )
        current_monday = current_date - datetime.timedelta(
            days=current_date.weekday(),
        )

        weeks = weeks_before + 1 + weeks_after
        start = selected_monday - datetime.timedelta(days=7 * weeks_before)
        boxes = [
            (
                start + datetime.timedelta(days=7 * week),
                start + datetime.timedelta(days=7 * week) == current_monday,
            )
            for week in range(weeks)
        ]

        return selected_monday, boxes

    @property
    def next_week(self) -> str:
        return (self.selected_monday + datetime.timedelta(days=7)).isoformat()

    @property
    def prev_week(self) -> str:
        return (self.selected_monday - datetime.timedelta(days=7)).isoformat()

    @property
    def next_month(self) -> str:
        return (self.selected_monday + datetime.timedelta(days=28)).isoformat()

    @property
    def prev_month(self) -> str:
        return (self.selected_monday - datetime.timedelta(days=28)).isoformat()

    @property
    def range_start(self) -> datetime.date:
        return self.boxes[0][0]

    @property
    def range_end(self) -> datetime.date:
        return self.boxes[-1][0] + datetime.timedelta(days=7)
