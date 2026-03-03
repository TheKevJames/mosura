import asyncio
import logging
from typing import Any

import fastapi
import jira

from . import database
from . import models
from . import schemas
from . import tasks


logger = logging.getLogger(__name__)
router = fastapi.APIRouter(tags=['api'])


@router.get('/issues', response_model=list[schemas.Issue])
async def read_issues(request: fastapi.Request) -> list[schemas.Issue]:
    async with database.session_from_app(request.app) as session:
        return await models.Issue.get(closed=False, session=session)


@router.get('/issues/{key}', response_model=schemas.Issue)
async def read_issue(request: fastapi.Request, key: str) -> schemas.Issue:
    async with database.session_from_app(request.app) as session:
        issues = await models.Issue.get(key=key, closed=True, session=session)

    if not issues:
        raise fastapi.HTTPException(
            status_code=fastapi.status.HTTP_404_NOT_FOUND,
        )

    return issues[0]


@router.patch('/issues/{key}', status_code=fastapi.status.HTTP_204_NO_CONTENT)
async def patch_issue(
        request: fastapi.Request,
        key: str,
        issue: schemas.IssuePatch,
) -> None:
    async with database.session_from_app(request.app) as session:
        issues = await models.Issue.get(key=key, closed=True, session=session)
        if not issues:
            raise fastapi.HTTPException(
                status_code=fastapi.status.HTTP_404_NOT_FOUND,
            )

        cached_issue = issues[0]
        live_issue = await asyncio.to_thread(
            request.app.state.jira_client.issue,
            id=cached_issue.key,
            fields=schemas.Issue.jira_fields(),
            expand='renderedFields',
        )
        if cached_issue != live_issue:
            tasks.schedule_issue_refresh(
                app=request.app,
                key=cached_issue.key,
            )
            raise fastapi.HTTPException(
                status_code=fastapi.status.HTTP_409_CONFLICT,
                detail=(
                    'This issue was modified in Jira while you were editing '
                    'it, please refresh the page and try again.'
                ),
            )

        new_data = issue.model_dump(exclude_unset=True)
        logger.info('updating %s with %r', cached_issue.key, new_data)

        await asyncio.to_thread(live_issue.update, fields=issue.to_jira())
        await models.Issue.upsert(
            cached_issue.model_copy(update=new_data),
            session=session,
        )
        await session.commit()


@router.get('/settings')
async def read_settings(
        request: fastapi.Request,
) -> dict[str, str | None]:
    async with database.session_from_app(request.app) as session:
        value = await models.Setting.get('custom_jql', session=session)
    return {'custom_jql': value}


@router.patch('/settings')
async def patch_settings(
        request: fastapi.Request,
        body: dict[str, Any],
) -> dict[str, Any]:
    custom_jql: str | None = body.get('custom_jql')

    if not custom_jql:
        async with database.session_from_app(request.app) as session:
            await models.Setting.delete('custom_jql', session=session)
            await session.commit()
        request.app.state.sync_event.set()
        return {'status': 'ok', 'custom_jql': None, 'issue_count': 0}

    try:
        result: dict[str, Any] = await asyncio.to_thread(
            request.app.state.jira_client.enhanced_search_issues,
            custom_jql,
            maxResults=1,
            json_result=True,
        )
    except jira.JIRAError as exc:
        raise fastapi.HTTPException(
            status_code=422,
            detail=exc.text,
        ) from exc

    async with database.session_from_app(request.app) as session:
        await models.Setting.upsert(
            'custom_jql', custom_jql, session=session,
        )
        await session.commit()

    request.app.state.sync_event.set()
    return {
        'status': 'ok',
        'custom_jql': custom_jql,
        'issue_count': result.get('total', 0),
    }


@router.get('/ping', status_code=fastapi.status.HTTP_204_NO_CONTENT)
async def ping() -> None:
    return None
