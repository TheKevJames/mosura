import logging

import fastapi

from . import crud
from . import schemas


logger = logging.getLogger(__name__)
router = fastapi.APIRouter(tags=['api'])


@router.get('/issues', response_model=list[schemas.Issue])
async def read_issues() -> list[schemas.Issue]:
    return await crud.read_issues()


@router.get('/issues/{key}', response_model=schemas.Issue)
async def read_issue(key: str) -> schemas.Issue:
    issue = await crud.read_issue(key)
    if not issue:
        raise fastapi.HTTPException(status_code=404)

    return issue


@router.get('/ping', status_code=fastapi.status.HTTP_204_NO_CONTENT)
async def ping() -> None:
    return None
