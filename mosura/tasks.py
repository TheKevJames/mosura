import asyncio
import datetime
import itertools
import logging
import random
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
            logger.debug(
                'fetch(%s): too soon, sleeping at least %ds',
                variant, (task.latest - now + interval).seconds,
            )
            await asyncio.sleep(random.uniform(0, 60))
            continue

        async with lock, database.session() as session:
            logger.info('fetch(%s): fetching data', variant)
            for idx in itertools.count(0, page_size):
                resp: dict[str, Any] = cast(
                    dict[str, Any],
                    await asyncio.to_thread(
                        config.jira_client.search_issues,
                        jql,
                        startAt=idx,
                        maxResults=page_size,
                        fields=schemas.Issue.jira_fields(),
                        expand='renderedFields',
                        json_result=True,
                    ),
                )
                issues: list[dict[str, Any]] = resp.get('issues', [])

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

                if resp['total'] < idx + page_size:
                    break

            logger.info(
                'fetch(%s): fetched %d issues in total', variant,
                resp['total'],
            )
            task = schemas.Task.model_validate({
                'key': 'fetch',
                'variant': variant,
                'latest': datetime.datetime.now(datetime.UTC),
            })
            await models.Task.upsert(task, session=session)
            await session.commit()


async def fetch_closed(project: str, lock: asyncio.Lock) -> None:
    await fetch(
        interval=datetime.timedelta(
            seconds=config.settings.mosura_poll_interval_closed,
        ),
        jql=(f"project = '{project}' AND status = 'Closed'"),
        lock=lock,
        variant='closed',
    )


async def fetch_open(project: str, lock: asyncio.Lock) -> None:
    await fetch(
        interval=datetime.timedelta(
            seconds=config.settings.mosura_poll_interval_open,
        ),
        jql=(f"project = '{project}' AND status != 'Closed'"),
        lock=lock,
        variant='open',
    )


async def spawn(project: str) -> set[asyncio.Task[None]]:
    try:
        _ = config.jira_client.project(project)
    except Exception:
        logger.exception('failed to query project "%s"', project)
        raise

    # TODO: shouldn't this be built into sqlalchemy?
    lock = asyncio.Lock()
    return {
        asyncio.create_task(fetch_closed(project, lock), name='fetch_closed'),
        asyncio.create_task(fetch_open(project, lock), name='fetch_open'),
    }
