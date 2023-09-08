import asyncio
import logging

import fastapi

from . import config
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
        raise fastapi.HTTPException(
            status_code=fastapi.status.HTTP_404_NOT_FOUND)

    return issues[0]


@router.patch('/issues/{key}', status_code=fastapi.status.HTTP_204_NO_CONTENT)
async def patch_issue(key: str, issue: schemas.IssuePatch) -> None:
    async with database.session() as session:
        issues = await models.Issue.get(key=key, closed=True, session=session)
        if not issues:
            raise fastapi.HTTPException(
                status_code=fastapi.status.HTTP_404_NOT_FOUND)

        cached_issue = issues[0]
        # TODO: debug the type issue
        live_issue = await asyncio.to_thread(
            config.jira_client.issue, id=cached_issue.key,
            fields=schemas.Issue.jira_fields(),  # type: ignore[arg-type]
            expand='renderedFields',
        )
        if cached_issue != live_issue:
            # TODO: need UI feedback
            raise fastapi.HTTPException(
                status_code=fastapi.status.HTTP_409_CONFLICT)

        new_data = issue.model_dump(exclude_unset=True)
        logger.info('updating %s with %r', cached_issue.key, new_data)

        await asyncio.to_thread(live_issue.update, fields=issue.to_jira())
        await models.Issue.upsert(cached_issue.model_copy(update=new_data),
                                  session=session)
        await session.commit()


@router.get('/ping', status_code=fastapi.status.HTTP_204_NO_CONTENT)
async def ping() -> None:
    return None
