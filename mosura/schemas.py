import datetime
import itertools
import logging
import warnings
from collections.abc import Iterable
from collections.abc import Iterator

import pydantic


with warnings.catch_warnings():
    warnings.simplefilter('ignore', DeprecationWarning)
    import jira


logger = logging.getLogger(__name__)


class Component(pydantic.BaseModel):
    key: str
    component: str

    class Config:
        orm_mode = True


class Label(pydantic.BaseModel):
    key: str
    label: str

    class Config:
        orm_mode = True


class IssueCreate(pydantic.BaseModel):
    key: str
    summary: str
    description: str | None
    status: str
    assignee: str | None
    priority: str
    startdate: datetime.datetime | None
    timeoriginalestimate: str

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

    class Config:
        orm_mode = True

    @property
    def body(self) -> str:
        return self.description or ''


class Task(pydantic.BaseModel):
    key: str
    variant: str
    latest: datetime.datetime

    class Config:
        orm_mode = True


@pydantic.dataclasses.dataclass(init=False)
class Meta:
    assignees: list[str]
    components: list[str]
    labels: list[str]
    priorities: list[str]
    statuses: list[str]

    def __init__(self, issues: list[Issue]):
        self.assignees = sorted({i.assignee for i in issues if i.assignee})
        self.components = sorted({c.component for i in issues
                                  for c in i.components})
        self.labels = sorted({lb.label for i in issues for lb in i.labels})
        self.priorities = sorted({i.priority for i in issues})
        self.statuses = sorted({i.status for i in issues})


@pydantic.dataclasses.dataclass(init=False)
class Quarter:
    year: int
    startmonth: int
    display: str
    padding: int

    def __init__(self, date: datetime.datetime | None = None,
                 padding: int = 7) -> None:
        date = date or datetime.datetime.now(datetime.UTC)

        self.padding = padding
        self.year = date.year if date.month > 1 else date.year - 1

        quarter = ((date.month - 2) // 3 + 1) or 4
        self.startmonth = {1: 2, 2: 5, 3: 8, 4: 11}[quarter]

        self.display = f'{self.year}Q{quarter}'

    @classmethod
    def from_display(cls, display: str | None, padding: int = 7) -> 'Quarter':
        if not display:
            return Quarter(padding=padding)

        year, quarter = display.split('Q', maxsplit=1)
        month = int(quarter) * 3

        date = datetime.datetime(year=int(year), month=month, day=1,
                                 tzinfo=datetime.UTC)
        return Quarter(date=date, padding=padding)

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


@pydantic.dataclasses.dataclass(init=False)
class Schedule:
    quarter: Quarter
    aligned: dict[str, list[tuple[int, Issue | None]]]
    raw: list[Issue]

    def __init__(self, issues: list[Issue],
                 quarter: Quarter | None = None) -> None:
        self.quarter = quarter or Quarter()

        in_quarter = [x for x in issues
                      if self.quarter.contains(x)
                      and x.assignee]
        invalid = [x for x in issues if x not in in_quarter]

        self.unaligned = []
        self.aligned = {}

        boxes = list(self.quarter.boxes)
        self._build_aligned(in_quarter, boxes)

        for issue in invalid[::-1]:
            data = self._get_unaligned_data(boxes, issue)
            if not data:
                invalid.remove(issue)
                continue

            self.unaligned.append(data)

        self.raw = list(in_quarter) + invalid

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


class Settings(pydantic.BaseSettings):
    jira_domain: str | None
    jira_label_okr: str
    jira_project: str | None
    # TODO: use pydantic.SecretStr once I figure out how to avoid making JS
    # double-secretify it
    jira_token: str | None
    jira_username: str | None

    @property
    def jira_client(self) -> jira.JIRA | None:
        if not (self.jira_domain and self.jira_token and self.jira_username):
            return None

        auth = (self.jira_username, self.jira_token)
        try:
            client = jira.JIRA(self.jira_domain, basic_auth=auth,
                               max_retries=0, validate=True)
        except Exception:
            logger.exception('failed to connect to jira')
            return None
        else:
            return client
