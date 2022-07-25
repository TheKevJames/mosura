import datetime
import itertools
from collections.abc import Iterator

import pydantic


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
        date = date or datetime.datetime.now(datetime.timezone.utc)

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
                                 tzinfo=datetime.timezone.utc)
        return Quarter(date=date, padding=padding)

    @property
    def _start(self) -> datetime.datetime:
        x = datetime.datetime(year=self.year, month=self.startmonth, day=1,
                              tzinfo=datetime.timezone.utc)
        if x.isoweekday() != 1:
            x += datetime.timedelta(days=8 - x.isoweekday())
        x -= datetime.timedelta(days=self.padding)
        return x

    @property
    def _end(self) -> datetime.datetime:
        x = datetime.datetime(year=self.year, month=self.startmonth + 3,
                              day=self.padding, tzinfo=datetime.timezone.utc)
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

    def pointer(
            self,
            date: datetime.datetime = datetime.datetime.now(
                datetime.timezone.utc),
    ) -> Iterator[bool]:
        for box in self.boxes:
            if box <= date < box + datetime.timedelta(days=7):
                yield True
                continue
            yield False


@pydantic.dataclasses.dataclass(init=False)
class Schedule:
    quarter: Quarter
    aligned: dict[str | None, list[tuple[int, Issue | None]]]
    raw: list[Issue]

    def __init__(self, issues: list[Issue],
                 quarter: Quarter | None = None) -> None:
        self.quarter = quarter or Quarter()

        def grouper(x: Issue) -> str:
            return x.assignee or ''

        self.raw = [x for x in issues if self.quarter.contains(x)]
        grouped = {k: list(v)
                   for k, v in itertools.groupby(
                       sorted(self.raw, key=grouper), grouper)}

        self.aligned = {k: [] for k in grouped}
        for assignee, assigned in grouped.items():
            boxes = list(self.quarter.boxes)
            idx = 0

            # TODO: account for projects which bled over from last quarter
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

                fills = -(-xs[0].timeestimate.days // 7)
                self.aligned[assignee].append((fills, xs[0]))
                idx += fills
