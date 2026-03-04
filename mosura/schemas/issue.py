import datetime
import enum
import logging
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
    def css_class(self) -> str:
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
    def sort_value(self) -> str:
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


class Status:
    @staticmethod
    def normalize_status(x: str) -> str:
        if x in {'To Do', 'Backlog'}:
            return 'backlog'
        if x == 'Needs Triage':
            return 'needs-triage'
        if x in {'Code Review', 'In Progress', 'Ready for Testing'}:
            return 'in-progress'
        if x in {'Closed', 'Done', 'Root Caused'}:
            return 'closed'
        return x.lower().replace(' ', '-')


class Component(pydantic.BaseModel):
    key: str
    component: str

    model_config = pydantic.ConfigDict(from_attributes=True)


class Label(pydantic.BaseModel):
    key: str
    label: str

    model_config = pydantic.ConfigDict(from_attributes=True)


class IssueTransition(pydantic.BaseModel):
    key: str
    from_status: str | None = None
    to_status: str
    timestamp: datetime.datetime

    model_config = pydantic.ConfigDict(from_attributes=True)


class IssueCreate(pydantic.BaseModel):
    key: str
    summary: str
    description: str | None = None
    status: str
    assignee: str | None = None
    priority: Priority
    startdate: datetime.date | None = None
    created: datetime.datetime
    updated: datetime.datetime
    timeestimate: datetime.timedelta
    votes: int

    @classmethod
    def jira_fields(cls) -> list[str]:
        return [
            'assignee',
            'components',
            'created',
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
            'updated',
            'votes',
        ]

    @classmethod
    def parse_datetime(cls, x: str) -> datetime.datetime:
        dt = datetime.datetime.fromisoformat(x)
        if dt.tzinfo is None:
            return dt.replace(tzinfo=datetime.UTC)
        return dt

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

    @staticmethod
    def parse_status(status: str) -> str:
        # This method should only be used for cases that we want to globally be
        # true, eg. to de-duplicate statuses with differing names in differing
        # projects. Do not use this method to make different statuses act the
        # same way, that should be done in `normalize_status()`.
        return {
            'To Do': 'Backlog',
            'Done': 'Closed',
            'Root Caused': 'Closed',
        }.get(status, status)

    @classmethod
    def from_jira(cls, data: dict[str, Any]) -> Self:
        # TODO: make this less stupid
        # TODO: two-way sync to keep these in sync?
        startdate_value = (
            data['fields']['customfield_12133']  # Start Date (cal)
            or data['fields'].get('customfield_12161')  # Start Date (issue)
        )
        startdate = (
            cls.parse_datetime(startdate_value).date()
            if startdate_value is not None
            else None
        )

        duedate_value = data['fields']['duedate']  # End Date (cal)
        duedate = (
            cls.parse_datetime(duedate_value).date()
            if duedate_value is not None
            else None
        )

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
            status=cls.parse_status(data['fields']['status']['name']),
            summary=data['fields']['summary'],
            startdate=startdate,
            created=cls.parse_datetime(data['fields']['created']),
            updated=cls.parse_datetime(data['fields']['updated']),
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
        return {
            'Needs Triage': 'stat0',
            'Backlog': 'stat1',
            'In Progress': 'stat2',
            'Code Review': 'stat3',
            'Ready for Testing': 'stat4',
            'Closed': 'stat5',
        }.get(self.status, 'stat9')


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
