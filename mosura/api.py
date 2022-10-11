import asyncio
import logging

import fastapi

from . import crud
from . import schemas
from . import tasks


logger = logging.getLogger(__name__)
router = fastapi.APIRouter(tags=['api'])


@router.post('/settings', status_code=fastapi.status.HTTP_201_CREATED)
async def create_settings(response: fastapi.Response,
                          settings: schemas.Settings) -> None:
    # TODO: debounce
    if settings.jira_domain:
        response.set_cookie(
            key='jira_domain', value=settings.jira_domain, httponly=True,
            samesite='strict', secure=True)
    if settings.jira_label_okr:
        response.set_cookie(
            key='jira_label_okr', value=settings.jira_label_okr, httponly=True,
            samesite='strict', secure=True)
    if settings.jira_project:
        response.set_cookie(
            key='jira_project', value=settings.jira_project, httponly=True,
            samesite='strict', secure=True)
    if settings.jira_token:
        response.set_cookie(
            key='jira_token', value=settings.jira_token, httponly=True,
            samesite='strict', secure=True)
    if settings.jira_username:
        response.set_cookie(
            key='jira_username', value=settings.jira_username, httponly=True,
            samesite='strict', secure=True)

    client = settings.jira_client
    if client:
        myself = client.myself()['displayName']
        logger.info('create_settings(): connected to jira as "%s"', myself)

        if settings.jira_project:
            try:
                _ = client.project(settings.jira_project)
            except Exception:
                logger.exception('failed to query project "%s"',
                                 settings.jira_project)
                return

            for t in asyncio.all_tasks():
                if t.get_name() in ('fetch_closed', 'fetch_open'):
                    t.cancel()

            asyncio.create_task(
                tasks.fetch_closed(client, settings.jira_project),
                name='fetch_closed')
            asyncio.create_task(
                tasks.fetch_open(client, settings.jira_project),
                name='fetch_open')
            logger.info('create_settings(): begun polling tasks for "%s"',
                        settings.jira_project)


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
