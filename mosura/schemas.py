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
    assignee: str
    priority: str


class IssueCreate(IssueBase):
    pass


class Issue(IssueBase):
    components: list[Component]
    labels: list[Label]

    class Config:
        orm_mode = True
