import asyncio
import datetime
import logging
from typing import Any
from typing import cast

from . import config
from . import database
from . import models
from . import schemas


logger = logging.getLogger(__name__)


async def fetch(
        *,
        variant: str,
        jql: str,
        lock: asyncio.Lock,
        interval: datetime.timedelta,
) -> None:
    # pylint: disable=too-many-locals
    page_size = 100
    logger.info(
        'fetch(%s): initialized with interval %ds', variant,
        interval.seconds,
    )

    while True:
        async with lock, database.session() as session:
            now = datetime.datetime.now(datetime.UTC)
            task = await models.Task.get('fetch', variant, session=session)

        if task and task.latest + interval > now:
            # add a second to avoid race conditions on idle instances
            sleep = (task.latest - now + interval).seconds + 1
            logger.debug('fetch(%s): too soon, sleeping %ds', variant, sleep)
            await asyncio.sleep(sleep)
            continue

        async with lock, database.session() as session:
            logger.info('fetch(%s): fetching data', variant)
            total_fetched = 0
            page_token: str | None = None
            while True:
                resp: dict[str, Any] = cast(
                    dict[str, Any],
                    await asyncio.to_thread(
                        config.jira_client.enhanced_search_issues,
                        jql,
                        nextPageToken=page_token,
                        maxResults=page_size,
                        fields=schemas.Issue.jira_fields(),
                        expand='renderedFields',
                        json_result=True,
                    ),
                )
                issues: list[dict[str, Any]] = resp.get('issues', [])
                total_fetched += len(issues)

                logger.debug(
                    'fetch(%s): fetched %d issues, writing to db',
                    variant, len(issues),
                )
                for issue in issues:
                    # TODO: in-place component and label upserts
                    await models.Component.delete(
                        issue['key'],
                        session=session,
                    )
                    for component in issue['fields']['components']:
                        await models.Component.upsert(
                            schemas.Component(
                                key=issue['key'],
                                component=component['name'],
                            ),
                            session=session,
                        )

                    await models.Label.delete(issue['key'], session=session)
                    for label in issue['fields']['labels']:
                        await models.Label.upsert(
                            schemas.Label(key=issue['key'], label=label),
                            session=session,
                        )

                    await models.Issue.upsert(
                        schemas.IssueCreate.from_jira(issue),
                        session=session,
                    )

                # N.B. resp['total'] is not provided for all responses, so we
                # need to count things ourselves.
                if len(issues) < page_size or resp.get('isLast') is True:
                    break
                page_token = resp.get('nextPageToken')

            logger.info(
                'fetch(%s): fetched %d issues in total', variant,
                total_fetched,
            )
            task = schemas.Task.model_validate({
                'key': 'fetch',
                'variant': variant,
                'latest': datetime.datetime.now(datetime.UTC),
            })
            await models.Task.upsert(task, session=session)
            await session.commit()


async def fetch_closed(
        lock: asyncio.Lock,
        project: str,
        users: list[str] | None = None,
) -> None:
    jql = f'project = "{project}" AND status IN ("Closed", "Done")'
    if users:
        # TODO: this filter means we stop getting updates for a ticket if it
        # gets reassigned away from a tracked user. Perhaps we could search the
        # assignee history? Or do an extra sync for any tickets in our DB but
        # not recently included in a fetch_ task?
        assignees = ','.join(f'"{x}"' for x in users)
        jql += f' AND assignee IN ({assignees})'
    await fetch(
        interval=datetime.timedelta(
            seconds=config.settings.mosura_poll_interval_closed,
        ),
        jql=jql,
        lock=lock,
        variant=f'{project}/closed',
    )


async def fetch_open(
        lock: asyncio.Lock,
        project: str,
        users: list[str] | None = None,
) -> None:
    jql = f'project = "{project}" AND status NOT IN ("Closed", "Done")'
    if users:
        assignees = ','.join(f'"{x}"' for x in users)
        jql += f' AND assignee IN ({assignees})'
    await fetch(
        interval=datetime.timedelta(
            seconds=config.settings.mosura_poll_interval_open,
        ),
        jql=jql,
        lock=lock,
        variant=f'{project}/open',
    )


async def spawn(users: list[str]) -> set[asyncio.Task[None]]:
    projects = config.settings.jira_projects
    for project in projects:
        try:
            _ = config.jira_client.project(project)
        except Exception:
            logger.exception('failed to query project "%s"', project)
            raise

    # TODO: shouldn't this be built into sqlalchemy?
    lock = asyncio.Lock()

    tasks = {
        asyncio.create_task(
            fetch_closed(lock, projects[0]),
            name=f'fetch_closed_{projects[0]}',
        ),
        asyncio.create_task(
            fetch_open(lock, projects[0]),
            name=f'fetch_open_{projects[0]}',
        ),
    }
    tasks.update({
        asyncio.create_task(
            fetch_closed(lock, p, users),
            name=f'fetch_closed_{p}',
        )
        for p in projects[1:]
    })
    tasks.update({
        asyncio.create_task(
            fetch_open(lock, p, users),
            name=f'fetch_open_{p}',
        )
        for p in projects[1:]
    })
    return tasks
