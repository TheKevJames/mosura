import datetime

import pydantic


class SettingValue(pydantic.BaseModel):
    value: str


class Task(pydantic.BaseModel):
    key: str
    variant: str
    latest: datetime.datetime

    model_config = pydantic.ConfigDict(from_attributes=True)
