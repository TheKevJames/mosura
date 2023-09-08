import datetime
import enum
import itertools
import logging
from collections.abc import Iterable
from collections.abc import Iterator
from typing import Any
from typing import assert_never
from typing import Self

import jira
import pydantic


logger = logging.getLogger(__name__)


class Priority(str, enum.Enum):
    # TODO: un-break support for jiras with non-default priorities
    low = 'Low'
    medium = 'Medium'
    high = 'High'
    urgent = 'Urgent'

    def __str__(self) -> str:
        return self.value

    @property
    def css_class(self) -> str:  # pylint: disable=inconsistent-return-statements
        if self == Priority.low:
            return 'green angle down icon'
        if self == Priority.medium:
            return 'yellow minus icon'
        if self == Priority.high:
            return 'orange angle up icon'
        if self == Priority.urgent:
            return 'red angle double up icon'
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
    startdate: datetime.datetime | None = None
    timeoriginalestimate: str

    @classmethod
    def jira_fields(cls) -> list[str]:
        return ['key', 'summary', 'description', 'status', 'assignee',
                'priority', 'components', 'labels', 'customfield_12161',
                'timeoriginalestimate']

    @classmethod
    def parse_datetime(cls, x: str | None) -> datetime.datetime | None:
        if x is None:
            return x
        return datetime.datetime.fromisoformat(x).replace(tzinfo=datetime.UTC)

    @classmethod
    def from_jira(cls, data: dict[str, Any]) -> Self:
        return cls(
            assignee=(data['fields']['assignee'] or {}).get('displayName'),
            description=data['renderedFields']['description'],
            key=data['key'],
            priority=data['fields']['priority']['name'],
            status=data['fields']['status']['name'],
            summary=data['fields']['summary'],
            startdate=cls.parse_datetime(data['fields']['customfield_12161']),
            timeoriginalestimate=str(data['fields'].get('timeoriginalestimate')
                                     or 0),
        )

    @property
    def timeestimate(self) -> datetime.timedelta:
        seconds_per_day = 60 * 60 * 8
        days_per_week = 5

        total_seconds = int(self.timeoriginalestimate)
        days = total_seconds // seconds_per_day
        days += (days // days_per_week) * 2
        seconds = total_seconds % seconds_per_day
        return datetime.timedelta(days=days, seconds=seconds)

    @property
    def enddate(self) -> datetime.datetime | None:
        if self.startdate is None:
            return None
        return self.startdate + self.timeestimate


class Issue(IssueCreate):
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
                mismatches.append(f'{field}: {getattr(self, field)} != '
                                  f'{getattr(parsed, field)}')

        if mismatches:
            logger.error('attempted update on out-of-sync issue %s:\n\t%s',
                         self.key, '\n\t'.join(mismatches))
            return False

        # TODO: components_equal and labels_equal
        return True


class IssuePatch(pydantic.BaseModel):
    # TODO: reminder to update Issue.__eq__ before adding support for
    # components or labels
    priority: Priority | None

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
        assignees = sorted({i.assignee for i in xs if i.assignee})
        components = sorted({c.component for i in xs for c in i.components})
        labels = sorted({lb.label for i in xs for lb in i.labels})
        priorities = sorted({i.priority for i in xs})
        statuses = sorted({i.status for i in xs})
        return cls(assignees, components, labels, priorities, statuses)


@pydantic.dataclasses.dataclass
class Quarter:
    year: int
    startmonth: int
    display: str
    padding: int

    @classmethod
    def init(cls, date: datetime.datetime | None = None,
             padding: int = 7) -> 'Quarter':
        date = date or datetime.datetime.now(datetime.UTC)
        year = date.year if date.month > 1 else date.year - 1

        quarter = ((date.month - 2) // 3 + 1) or 4
        startmonth = {1: 2, 2: 5, 3: 8, 4: 11}[quarter]

        display = f'{year}Q{quarter}'
        return cls(year, startmonth, display, padding)

    @classmethod
    def from_display(cls, display: str | None, padding: int = 7) -> 'Quarter':
        if not display:
            return Quarter.init(padding=padding)

        year, quarter = display.split('Q', maxsplit=1)
        month = int(quarter) * 3

        date = datetime.datetime(year=int(year), month=month, day=1,
                                 tzinfo=datetime.UTC)
        return Quarter.init(date=date, padding=padding)

    @property
    def _start(self) -> datetime.datetime:
        x = datetime.datetime(year=self.year, month=self.startmonth, day=1,
                              tzinfo=datetime.UTC)
        if x.isoweekday() != 1:
            x += datetime.timedelta(days=8 - x.isoweekday())
        x -= datetime.timedelta(days=self.padding)
        return x

    @property
    def _end(self) -> datetime.datetime:
        x = datetime.datetime(year=self.year, month=self.startmonth + 3,
                              day=self.padding, tzinfo=datetime.UTC)
        return x

    @property
    def boxes(self) -> Iterator[datetime.datetime]:
        curr = self._start
        while curr < self._end:
            yield curr
            curr += datetime.timedelta(days=7)

    @property
    def headers(self) -> Iterator[tuple[int, bool, datetime.datetime]]:
        boxes = list(self.boxes)
        padding = {boxes[0].month, boxes[-1].month}
        for box, group in itertools.groupby(boxes, lambda x: x.month):
            xs = list(group)
            yield len(xs), box in padding, xs[0]

    def contains(self, x: Issue) -> bool:
        startdate = x.startdate
        if not startdate:
            return False

        enddate = x.enddate
        if not enddate:
            return False

        return enddate > self._start and startdate < self._end

    def display_offset(self, offset: int) -> str:
        year, quarter = (int(x) for x in self.display.split('Q', maxsplit=1))

        year += (abs(offset) // offset) * (abs(offset) // 4)
        quarter += offset
        return f'{year}Q{quarter}'

    def pointer(
            self,
            date: datetime.datetime = datetime.datetime.now(datetime.UTC),
    ) -> Iterator[bool]:
        for box in self.boxes:
            if box <= date < box + datetime.timedelta(days=7):
                yield True
                continue
            yield False

    def uncontained(self, x: Issue) -> bool:
        startdate = x.startdate
        if not startdate:
            return False

        enddate = x.enddate
        if not enddate:
            return False

        return startdate > self._end or enddate < self._start


@pydantic.dataclasses.dataclass
class Schedule:
    quarter: Quarter
    unaligned: list[tuple[int, int, Issue]]
    aligned: dict[str, list[tuple[int, Issue | None]]]
    raw: list[Issue]

    @classmethod
    def init(cls, issues: list[Issue],
             quarter: Quarter | None = None) -> 'Schedule':
        self = cls(quarter or Quarter.init(), [], {}, [])

        in_quarter = [x for x in issues
                      if self.quarter.contains(x)
                      and x.assignee]
        invalid = [x for x in issues if x not in in_quarter]

        boxes = list(self.quarter.boxes)
        self._build_aligned(in_quarter, boxes)

        for issue in invalid[::-1]:
            data = self._get_unaligned_data(boxes, issue)
            if not data:
                invalid.remove(issue)
                continue

            self.unaligned.append(data)

        self.raw = list(in_quarter) + invalid
        return self

    def _build_aligned(self, issues: Iterable[Issue],
                       boxes: list[datetime.datetime]) -> None:
        def grouper(x: Issue) -> str:
            return x.assignee or ''

        grouped = {k: list(v) for k, v in itertools.groupby(
            sorted(issues, key=grouper), grouper)}
        self.aligned = {k: [] for k in grouped}

        for assignee, assigned in grouped.items():
            xs = [x for x in assigned
                  if x.startdate and x.startdate < boxes[0]]
            if xs:
                x = xs.pop()
                assert x.enddate, 'enddate missing for aligned data'
                fills = -(-(x.enddate - boxes[0]).days // 7)
                self.aligned[assignee].append((fills, x))
                self._handle_overlap(xs, 0)

            idx = 1
            while idx < len(boxes):
                box = boxes[idx]
                xs = [x for x in assigned
                      if x.startdate
                      if box <= x.startdate
                      and x.startdate < box + datetime.timedelta(days=7)]
                if not xs:
                    self.aligned[assignee].append((1, None))
                    idx += 1
                    continue

                x = xs.pop()
                fills = -(-x.timeestimate.days // 7)
                self.aligned[assignee].append((fills, x))
                self._handle_overlap(xs, idx)
                idx += fills

    def _handle_overlap(self, xs: list[Issue], idx: int) -> None:
        """Handle overlapping Issues by marking 'em as unaligned."""
        for x in xs:
            fill = -(-x.timeestimate.days // 7)
            self.unaligned.append((idx, fill, x))

    @staticmethod
    def _get_unaligned_data(boxes: list[datetime.datetime],
                            x: Issue) -> tuple[int, int, Issue] | None:
        if x.startdate:
            for idx, box in enumerate(boxes):
                if (box <= x.startdate
                        and (x.startdate < box + datetime.timedelta(days=7))):
                    break
            else:
                return None
        else:
            idx = 1

        if x.timeestimate:
            fills = -(-x.timeestimate.days // 7)
        else:
            fills = len(boxes) - 2

        return (idx, fills, x)
