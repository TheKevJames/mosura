import datetime

import pydantic


class ComponentBase(pydantic.BaseModel):
    component: str


class ComponentCreate(ComponentBase):
    pass


class Component(ComponentBase):
    key: str

    class Config:
        orm_mode = True


class LabelBase(pydantic.BaseModel):
    label: str


class LabelCreate(LabelBase):
    pass


class Label(LabelBase):
    key: str

    class Config:
        orm_mode = True


class IssueBase(pydantic.BaseModel):
    key: str
    summary: str
    description: str | None
    status: str
    assignee: str | None
    priority: str


class IssueCreate(IssueBase):
    pass


class Issue(IssueBase):
    components: list[Component]
    labels: list[Label]

    class Config:
        orm_mode = True

    @property
    def body(self) -> str:
        # TODO: apply additional formatting
        return self.description or ''


class TaskBase(pydantic.BaseModel):
    key: str
    variant: str
    latest: datetime.datetime


class TaskCreate(TaskBase):
    pass


class Task(TaskBase):
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
