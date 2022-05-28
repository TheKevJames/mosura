import fastapi

from . import crud
from . import models
from . import schemas


api_v0 = fastapi.FastAPI()

api = fastapi.FastAPI()
api.mount('/v0', api_v0)


@api_v0.get('/issues', response_model=list[schemas.Issue])
async def read_issues(offset: int = 0,
                      limit: int = 100) -> list[models.Issue]:
    return await crud.get_issues(offset=offset, limit=limit)


@api_v0.get('/issues/{key}', response_model=schemas.Issue)
async def read_issue(key: str) -> models.Issue:
    return await crud.get_issue(key)
