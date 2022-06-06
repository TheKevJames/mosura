import datetime

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
