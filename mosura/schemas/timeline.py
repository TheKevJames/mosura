import datetime
import logging

import pydantic

from mosura.schemas.issue import Issue
from mosura.schemas.issue import IssueCreate
from mosura.schemas.issue import IssueTransition


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


def getsummary(x: Issue) -> str:
    return x.summary


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
            transitions: dict[str, list[IssueTransition]] | None = None,
            selected_date: datetime.date | None = None,
            current_date: datetime.date | None = None,
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
        # pylint: disable=too-many-locals
        if transitions is None:
            transitions = {}

        resolved_current_date = (
            current_date
            or datetime.datetime.now(datetime.UTC).date()
        )
        resolved_selected_date = selected_date or resolved_current_date

        selected_monday, boxes = cls.get_boxes(
            selected_date=resolved_selected_date,
            current_date=resolved_current_date,
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
            should_attend = cls._should_attend(
                issue,
                transitions.get(issue.key, []),
                resolved_current_date,
                view_start=view_start,
            )

            if should_attend:
                attention_issues.append(issue)
            else:
                # Build timeline issue from transitions
                tli = cls._build_timeline_issue(
                    issue,
                    transitions.get(issue.key, []),
                    resolved_current_date,
                    view_start,
                    view_end,
                )
                if tli:
                    timeline_issues.append(tli)

        # Sort attention by summary
        attention_issues.sort(key=getsummary)
        # Sort timeline by created date
        timeline_issues.sort(key=lambda x: x.created)

        return cls(
            timeline_issues,
            attention_issues,
            selected_monday,
            boxes,
        )

    @staticmethod
    def _should_attend(
            issue: Issue,
            trans: list[IssueTransition],
            current_date: datetime.date,
            view_start: datetime.date | None = None,
    ) -> bool:
        """
        Determine if an issue should be in the attention list.

        Issues go to attention if:
        - They have no timeestimate (zero timedelta)
        - OR they have overdue_start AND startdate < view_start
        """
        if Timeline._is_closed_status(issue.status):
            return False

        # No timeestimate (zero timedelta) → needs attention
        if issue.timeestimate == datetime.timedelta(0):
            return True

        # Check for overdue_start condition
        # Issue has started if: has In Progress transition, or current status
        # shows progress
        has_in_progress = (
            any(t.to_status == 'In Progress' for t in trans)
            or issue.status in ('In Progress', 'Code Review')
        )
        if (
            issue.startdate
            and issue.startdate < current_date
            and not has_in_progress
        ):
            # Only put in attention if startdate is before the view window
            if view_start and issue.startdate < view_start:
                return True

        return False

    @staticmethod
    def _normalize_status(status: str | None) -> str | None:
        if status is None:
            return None
        return IssueCreate.parse_status(status)

    @staticmethod
    def _is_closed_status(status: str | None) -> bool:
        return Timeline._normalize_status(status) == 'Closed'

    @staticmethod
    def _build_timeline_issue(
            issue: Issue,
            trans: list[IssueTransition],
            current_date: datetime.date,
            view_start: datetime.date,
            view_end: datetime.date,
    ) -> TimelineIssue | None:
        """Build a TimelineIssue from an issue and its transitions."""
        # pylint: disable=too-many-locals,too-many-branches,too-complex
        created_date = (
            issue.created.date()
            if isinstance(issue.created, datetime.datetime)
            else issue.created
        )

        # Build segments from transitions
        segments: list[TimelineSegment] = []
        issue_status = (
            Timeline._normalize_status(issue.status) or issue.status
        )

        if not trans:
            # No transitions: single segment from created to estimated/closed
            segment_end = Timeline._compute_estimated_completion(
                issue, trans,
            )
            if (
                segment_end is None
                and Timeline._is_closed_status(issue.status)
            ):
                segment_end = issue.updated.date()
            if not Timeline._is_closed_status(issue.status):
                segment_end = max(segment_end or current_date, current_date)
            else:
                segment_end = segment_end or current_date
            segments.append(
                TimelineSegment(
                    start=created_date,
                    end=segment_end,
                    status=issue.status,
                ),
            )
        else:
            first_trans = trans[0]
            initial_status = first_trans.from_status or issue.status
            segments.append(
                TimelineSegment(
                    start=created_date,
                    end=first_trans.timestamp.date(),
                    status=initial_status,
                ),
            )

            for i, transition in enumerate(trans[:-1]):
                segments.append(
                    TimelineSegment(
                        start=transition.timestamp.date(),
                        end=trans[i + 1].timestamp.date(),
                        status=transition.to_status,
                    ),
                )

            last_trans = trans[-1]
            if Timeline._is_closed_status(last_trans.to_status):
                segments.append(
                    TimelineSegment(
                        start=last_trans.timestamp.date(),
                        end=last_trans.timestamp.date(),
                        status=last_trans.to_status,
                    ),
                )
            else:
                est_complete = Timeline._compute_estimated_completion(
                    issue, trans,
                )
                segment_end = max(est_complete or current_date, current_date)
                segments.append(
                    TimelineSegment(
                        start=last_trans.timestamp.date(),
                        end=segment_end,
                        status=last_trans.to_status,
                    ),
                )

        # Log inverted segments: this indicates a logic bug.
        for segment in segments:
            if segment.start > segment.end:
                logger.error(
                    'timeline segment has inverted dates '
                    'for %s (%s): %s > %s',
                    issue.key,
                    segment.status,
                    segment.start,
                    segment.end,
                )

        # Clamp segments to view window and keep visible segments only.
        clamped_segments: list[TimelineSegment] = []
        view_end_inclusive = view_end - datetime.timedelta(days=1)
        for segment in segments:
            segment.start = max(segment.start, view_start)
            segment.end = min(segment.end, view_end_inclusive)
            if segment.start <= segment.end:
                clamped_segments.append(segment)
        segments = clamped_segments

        # Compute flags
        est_completion = Timeline._compute_estimated_completion(
            issue, trans,
        )
        overdue = bool(
            est_completion
            and est_completion < current_date
            and not Timeline._is_closed_status(issue.status),
        )

        has_in_progress = (
            any(t.to_status == 'In Progress' for t in trans)
            or issue.status in ('In Progress', 'Code Review')
        )
        overdue_start = bool(
            issue.startdate
            and issue.startdate < current_date
            and not has_in_progress
            and not Timeline._is_closed_status(issue.status),
        )

        if not segments:
            return None

        return TimelineIssue(
            key=issue.key,
            summary=issue.summary,
            status=issue_status,
            created=created_date,
            startdate=issue.startdate,
            segments=segments,
            estimated_completion=est_completion,
            overdue=overdue,
            overdue_start=overdue_start,
        )

    @staticmethod
    def _compute_estimated_completion(
            issue: Issue,
            trans: list[IssueTransition],
    ) -> datetime.date | None:
        """Compute estimated completion date for an issue."""
        if Timeline._is_closed_status(issue.status):
            # Closed issues: find close transition
            close_trans = next(
                (t for t in trans if Timeline._is_closed_status(t.to_status)),
                None,
            )
            if close_trans:
                return close_trans.timestamp.date()
            return None

        # Look for In Progress transition
        in_prog_trans = next(
            (t for t in trans if t.to_status == 'In Progress'),
            None,
        )

        if in_prog_trans and issue.timeestimate:
            base_date = in_prog_trans.timestamp.date()
            days = max(issue.timeestimate.days - 1, 0)
            return base_date + datetime.timedelta(days=days)

        # No In Progress, use startdate if available
        if issue.startdate and issue.timeestimate:
            days = max(issue.timeestimate.days - 1, 0)
            return issue.startdate + datetime.timedelta(days=days)

        return None

    @staticmethod
    def get_boxes(
            selected_date: datetime.date | None,
            current_date: datetime.date | None,
            weeks_before: int,
            weeks_after: int,
    ) -> tuple[datetime.date, list[tuple[datetime.date, bool]]]:
        resolved_current_date = (
            current_date
            or datetime.datetime.now(datetime.UTC).date()
        )
        resolved_selected_date = selected_date or resolved_current_date

        selected_monday = resolved_selected_date - datetime.timedelta(
            days=resolved_selected_date.weekday(),
        )
        current_monday = resolved_current_date - datetime.timedelta(
            days=resolved_current_date.weekday(),
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
