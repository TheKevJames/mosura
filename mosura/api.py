import fastapi

from . import crud
from . import schemas


api_v0 = fastapi.FastAPI()

api = fastapi.FastAPI()
api.mount('/v0', api_v0)


@api_v0.get('/issues', response_model=list[schemas.Issue])
async def read_issues(offset: int = 0,
                      limit: int = 100) -> list[schemas.Issue]:
    return await crud.read_issues(offset=offset, limit=limit)


@api_v0.get('/issues/{key}', response_model=schemas.Issue)
async def read_issue(key: str) -> schemas.Issue:
    issue = await crud.read_issue(key)
    if not issue:
        raise fastapi.HTTPException(status_code=404)

    return issue
