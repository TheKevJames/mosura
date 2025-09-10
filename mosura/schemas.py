import datetime
import enum
import itertools
import logging
from collections.abc import Iterable
from typing import Any
from typing import assert_never
from typing import Self

import jira
import pydantic


logger = logging.getLogger(__name__)


class Priority(str, enum.Enum):
    # TODO: un-break support for jiras with non-default priorities
    unknown = 'No priority'
    low = 'Low'
    medium = 'Medium'
    high = 'High'
    urgent = 'Urgent'

    def __str__(self) -> str:
        return self.value

    @property
    def css_class(self) -> str:  # pylint: disable=inconsistent-return-statements
        if self == Priority.unknown:
            return 'grey question circle icon'
        if self == Priority.low:
            return 'green angle down icon'
        if self == Priority.medium:
            return 'yellow minus icon'
        if self == Priority.high:
            return 'orange angle up icon'
        if self == Priority.urgent:
            return 'red angle double up icon'
        assert_never(self)

    @property
    def sort_value(self) -> str:  # pylint: disable=inconsistent-return-statements
        if self == Priority.unknown:
            return 'pri0'
        if self == Priority.low:
            return 'pri1'
        if self == Priority.medium:
            return 'pri2'
        if self == Priority.high:
            return 'pri3'
        if self == Priority.urgent:
            return 'pri4'
        assert_never(self)


class Component(pydantic.BaseModel):
    key: str
    component: str

    model_config = pydantic.ConfigDict(from_attributes=True)


class Label(pydantic.BaseModel):
    key: str
    label: str

    model_config = pydantic.ConfigDict(from_attributes=True)


class IssueCreate(pydantic.BaseModel):
    key: str
    summary: str
    description: str | None = None
    status: str
    assignee: str | None = None
    priority: Priority
    startdate: datetime.date | None = None
    timeestimate: datetime.timedelta
    votes: int

    @classmethod
    def jira_fields(cls) -> list[str]:
        return [
            'assignee',
            'components',
            'customfield_12133',
            'customfield_12161',
            'description',
            'duedate',
            'key',
            'labels',
            'priority',
            'status',
            'summary',
            'timeoriginalestimate',
            'votes',
        ]

    @classmethod
    def parse_date(cls, x: str | None) -> datetime.date | None:
        if x is None:
            return x
        return datetime.datetime.fromisoformat(x).replace(
            tzinfo=datetime.UTC,
        ).date()

    @classmethod
    def parse_timeestimate(cls, total_seconds: str) -> datetime.timedelta:
        # the timeoriginalestimate field lets you type, eg. "3w", but then
        # encodes that time as the number of seconds... assuming a 40 day work
        # week
        seconds_per_day = 60 * 60 * 8
        days_per_week = 5

        days = int(total_seconds) // seconds_per_day
        days += (days // days_per_week) * 2
        seconds = int(total_seconds) % seconds_per_day
        return datetime.timedelta(days=days, seconds=seconds)

    @classmethod
    def from_jira(cls, data: dict[str, Any]) -> Self:
        # normalizations
        status = data['fields']['status']['name']
        status = {
            'To Do': 'Backlog',
            'Done': 'Closed',
        }.get(status, status)

        # TODO: make this less stupid
        # TODO: two-way sync to keep these in sync?
        startdate = cls.parse_date(
            data['fields']['customfield_12133']  # Start Date (cal)
            or data['fields']['customfield_12161'],  # Start Date (issue)
        )
        duedate = cls.parse_date(data['fields']['duedate'])  # End Date (cal)
        if duedate is not None and startdate is not None:
            timeestimate = duedate - startdate
        else:
            timeestimate = cls.parse_timeestimate(
                data['fields'].get('timeoriginalestimate') or '0',
            )

        # TODO: handle relative links in description, eg. for <img src="/rest
        return cls(
            assignee=(data['fields']['assignee'] or {}).get('displayName'),
            description=data['renderedFields']['description'],
            key=data['key'],
            priority=data['fields']['priority']['name'],
            status=status,
            summary=data['fields']['summary'],
            startdate=startdate,
            timeestimate=timeestimate,
            votes=data['fields']['votes']['votes'],
        )

    @property
    def enddate(self) -> datetime.date | None:
        if self.startdate is None:
            return None
        return self.startdate + self.timeestimate

    @property
    def status_sort_value(self) -> str:
        if self.status == 'Needs Triage':
            return 'stat0'
        if self.status == 'Backlog':
            return 'stat1'
        if self.status == 'In Progress':
            return 'stat2'
        if self.status == 'Code Review':
            return 'stat3'
        if self.status == 'Closed':
            return 'stat4'
        return 'stat9'


class Issue(IssueCreate):
    # TODO: implement __hash__, use sets for perf throughout
    components: list[Component]
    labels: list[Label]

    model_config = pydantic.ConfigDict(from_attributes=True)

    @property
    def body(self) -> str:
        return self.description or ''

    def __eq__(self, other: Any) -> bool:
        if not isinstance(other, jira.Issue):
            return super().__eq__(other)

        parsed = IssueCreate.from_jira(other.raw)

        mismatches: list[str] = []
        for field in IssueCreate.model_fields:
            check = getattr(self, field) == getattr(parsed, field)
            if not check:
                mismatches.append(
                    f'{field}: {getattr(self, field)} != '
                    f'{getattr(parsed, field)}',
                )

        if mismatches:
            logger.error(
                'attempted update on out-of-sync issue %s:\n\t%s',
                self.key, '\n\t'.join(mismatches),
            )
            return False

        # TODO: components_equal and labels_equal
        return True


class IssuePatch(pydantic.BaseModel):
    # TODO: reminder to update Issue.__eq__ before adding support for
    # components or labels
    priority: Priority | None = None
    summary: str | None = None

    model_config = pydantic.ConfigDict(use_enum_values=True)

    def to_jira(self) -> dict[str, str | dict[str, str]]:
        data = self.model_dump(exclude_unset=True)
        if data.get('priority'):
            data['priority'] = {'name': data['priority']}
        return data


class Task(pydantic.BaseModel):
    key: str
    variant: str
    latest: datetime.datetime

    model_config = pydantic.ConfigDict(from_attributes=True)


@pydantic.dataclasses.dataclass
class Meta:
    assignees: list[str]
    components: list[str]
    labels: list[str]
    priorities: list[Priority]
    statuses: list[str]

    @classmethod
    def from_issues(cls, xs: list[Issue]) -> 'Meta':
        assignees = sorted({i.assignee for i in xs if i.assignee}) + ['None']
        components = sorted({c.component for i in xs for c in i.components})
        labels = sorted({lb.label for i in xs for lb in i.labels})
        priorities = sorted({i.priority for i in xs})
        statuses = sorted({i.status for i in xs})
        return cls(assignees, components, labels, priorities, statuses)


Aligned = list[list[tuple[int, Issue | None]]]


def getassignee(x: Issue) -> str:
    return x.assignee or 'Unassigned'


def getsummary(x: Issue) -> str:
    return x.summary


def sortdate(x: Issue) -> datetime.date:
    return x.startdate or datetime.date.min


@pydantic.dataclasses.dataclass
class Timeline:
    aligned: dict[str, Aligned]
    triage: list[Issue]
    monday: datetime.date
    boxes: list[tuple[datetime.date, bool]]

    @classmethod
    def from_issues(
            cls,
            issues: list[Issue],
            *,
            okr_label: str | None = None,
            target: datetime.date | None = None,
            weeks_before: int = 3,
            weeks_after: int = 10,
    ) -> 'Timeline':
        aligned: dict[str, Aligned] = {}
        triage: list[Issue] = []
        monday, boxes = cls.get_boxes(target, weeks_before, weeks_after)

        groups = itertools.groupby(
            sorted(issues, key=getassignee),
            getassignee,
        )
        for assignee, candidates in groups:
            aligning, triaging = cls.partition_issues(
                candidates,
                boxes[0][0],
                boxes[-1][0] + datetime.timedelta(days=7),
                okr_label,
            )
            aligned[assignee] = cls.align_issues(
                sorted(aligning, key=sortdate),
                boxes[0][0],
                boxes[-1][0] + datetime.timedelta(days=7),
            )
            triage.extend(sorted(triaging, key=getsummary))

        return cls(aligned, triage, monday, boxes)

    @staticmethod
    def partition_issues(
            issues: Iterable[Issue],
            start_date: datetime.date,
            end_date: datetime.date,
            okr_label: str | None,
    ) -> tuple[list[Issue], list[Issue]]:
        aligning: list[Issue] = []
        triage: list[Issue] = []

        for x in issues:
            is_okr = okr_label and okr_label in {x.label for x in x.labels}
            if not x.assignee and not is_okr:
                # only track unassigned issues if they are OKRs
                continue

            if x.status != 'Closed' and not (x.startdate and x.enddate):
                triage.append(x)
            if x.startdate and x.startdate >= end_date:
                # don't render future events
                continue
            if x.enddate and x.enddate > start_date:
                aligning.append(x)

        return aligning, triage

    @staticmethod
    def get_boxes(
            target: datetime.date | None,
            weeks_before: int,
            weeks_after: int,
    ) -> tuple[datetime.date, list[tuple[datetime.date, bool]]]:
        now = target or datetime.datetime.now(datetime.UTC).date()
        monday = now - datetime.timedelta(days=now.weekday())

        weeks = weeks_before + 1 + weeks_after
        start = monday - datetime.timedelta(days=7 * weeks_before)
        boxes = [
            (
                start + datetime.timedelta(days=7 * week),
                week >= weeks_before,
            )
            for week in range(weeks)
        ]

        return monday, boxes

    @classmethod
    def align_issues(
            cls,
            issues: list[Issue],
            start: datetime.date,
            end: datetime.date,
    ) -> Aligned:
        """
        Aligns issues into rows of non-overlapping spans.

        Packs optimally when issues is sorted by start date.
        """
        assigned: Aligned = []
        for x in issues:
            assert x.startdate, 'cannot align issues without startdate'
            assert x.enddate, 'cannot align issues without enddate'

            # clamp rendering to current view
            target = max(x.startdate, start)
            enddate = min(x.enddate, end)
            fills = -(-(enddate - target).days // 7)

            first_empty: datetime.date
            row: list[tuple[int, Issue | None]]
            for row in assigned:
                filled = sum(x[0] for x in row)
                first_empty = start + datetime.timedelta(days=7 * filled)
                if first_empty <= target:
                    break
            else:
                row = []
                assigned.append(row)
                first_empty = start

            gap = (target - first_empty).days // 7
            if gap:
                row.append((gap, None))

            row.append((fills, x))

        return assigned

    @property
    def next_month(self) -> str:
        return (self.monday + datetime.timedelta(days=28)).isoformat()

    @property
    def prev_month(self) -> str:
        return (self.monday - datetime.timedelta(days=28)).isoformat()
