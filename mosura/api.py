import logging

import fastapi

from . import database
from . import models
from . import schemas


logger = logging.getLogger(__name__)
router = fastapi.APIRouter(tags=['api'])


@router.get('/issues', response_model=list[schemas.Issue])
async def read_issues() -> list[schemas.Issue]:
    async with database.session() as session:
        return await models.Issue.get(closed=False, session=session)


@router.get('/issues/{key}', response_model=schemas.Issue)
async def read_issue(key: str) -> schemas.Issue:
    async with database.session() as session:
        issues = await models.Issue.get(key=key, closed=True, session=session)

    if not issues:
        raise fastapi.HTTPException(status_code=404)

    return issues[0]


@router.get('/ping', status_code=fastapi.status.HTTP_204_NO_CONTENT)
async def ping() -> None:
    return None
