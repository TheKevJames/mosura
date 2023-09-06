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


def datetime_or_null(x: str | None) -> datetime.datetime | None:
    if x is None:
        return x
    return datetime.datetime.fromisoformat(x)


async def fetch(
        *,
        variant: str,
        jql: str,
        interval: datetime.timedelta,
) -> None:
    page_size = 100
    fields = ['key', 'summary', 'description', 'status', 'assignee',
              'priority', 'components', 'labels', 'customfield_12161',
              'timeoriginalestimate']

    while True:
        async with database.session() as session:
            now = datetime.datetime.now(datetime.UTC)
            task = await models.Task.get('fetch', variant, session=session)
            if task and task.latest + interval > now:
                logger.debug('fetch(%s): too soon, sleeping at least %ds',
                             variant, (task.latest - now + interval).seconds)
                await asyncio.sleep(random.uniform(0, 60))
                continue

            logger.info('fetch(%s): fetching data', variant)

            for idx in itertools.count(0, page_size):
                issues: dict[str, Any] = cast(
                    dict[str, Any],
                    await asyncio.to_thread(
                        config.jira_client.search_issues,
                        jql,
                        startAt=idx,
                        maxResults=page_size,
                        fields=fields,
                        expand='renderedFields',
                        json_result=True,
                    ),
                )
                logger.debug('fetch(%s): fetched %d issues, writing to db',
                             variant, len(issues.get('issues', [])))
                for issue in issues.get('issues', []):
                    # TODO: in-place component and label upserts
                    await models.Component.delete(issue['key'],
                                                  session=session)
                    for component in issue['fields']['components']:
                        await models.Component.upsert(
                            schemas.Component(key=issue['key'],
                                              component=component['name']),
                            session=session,
                        )

                    await models.Label.delete(issue['key'], session=session)
                    for label in issue['fields']['labels']:
                        await models.Label.upsert(
                            schemas.Label(key=issue['key'], label=label),
                            session=session,
                        )

                    await models.Issue.upsert(
                        schemas.IssueCreate(
                            assignee=(issue['fields']['assignee']
                                      or {}).get('displayName'),
                            description=issue['renderedFields']['description'],
                            key=issue['key'],
                            priority=issue['fields']['priority']['name'],
                            status=issue['fields']['status']['name'],
                            summary=issue['fields']['summary'],
                            startdate=datetime_or_null(
                                issue['fields']['customfield_12161']),
                            timeoriginalestimate=str(
                                issue['fields'].get('timeoriginalestimate')
                                or 0),
                        ),
                        session=session,
                    )

                if issues['total'] < idx + page_size:
                    break

            logger.info('fetch(%s): fetched %d issues in total', variant,
                        issues['total'])
            task = schemas.Task.model_validate({
                'key': 'fetch',
                'variant': variant,
                'latest': datetime.datetime.now(datetime.UTC)})
            await models.Task.upsert(task, session=session)
            await session.commit()


async def fetch_closed(project: str) -> None:
    await fetch(
        interval=datetime.timedelta(minutes=15),
        jql=(f"project = '{project}' "
             "AND status = 'Closed'"),
        variant='closed',
    )


async def fetch_open(project: str) -> None:
    await fetch(
        interval=datetime.timedelta(minutes=5),
        jql=(f"project = '{project}' "
             "AND status != 'Closed'"),
        variant='open',
    )


async def spawn(project: str) -> set[asyncio.Task[None]]:
    try:
        _ = config.jira_client.project(project)
    except Exception:
        logger.exception('failed to query project "%s"', project)
        raise

    return {
        asyncio.create_task(fetch_closed(project), name='fetch_closed'),
        asyncio.create_task(fetch_open(project), name='fetch_open'),
    }
