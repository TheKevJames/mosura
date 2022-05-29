import asyncio
import datetime
import itertools
import logging
import random
from typing import Any
from typing import cast

import jira

from . import config
from . import crud
from . import schemas


logger = logging.getLogger(__name__)


async def fetch(client: jira.JIRA, *, variant: str, jql: str,
                interval: datetime.timedelta) -> None:
    page_size = 100
    fields = ['key', 'summary', 'description', 'status', 'assignee',
              'priority', 'components', 'labels']

    while True:
        now = datetime.datetime.now(datetime.timezone.utc)
        task = await crud.read_task('fetch', variant)
        if task and task.latest + interval > now:
            logger.debug('fetch(%s): too soon, sleeping at least %ds', variant,
                         (task.latest - now + interval).seconds)
            await asyncio.sleep(random.uniform(0, 60))
            continue

        logger.info('fetch(%s): fetching data', variant)

        for idx in itertools.count(0, page_size):
            issues: dict[str, Any] = cast(dict[str, Any],
                                          await asyncio.to_thread(
                client.search_issues, jql, startAt=idx, maxResults=page_size,
                fields=fields, expand='renderedFields', json_result=True))
            logger.debug('fetch(%s): fetched %d issues, writing to localdb',
                         variant, len(issues.get('issues', [])))
            for issue in issues.get('issues', []):
                for component in issue['fields']['components']:
                    await crud.upsert_issue_component(
                        schemas.Component(key=issue['key'],
                                          component=component['name']))

                for label in issue['fields']['labels']:
                    await crud.upsert_issue_label(
                        schemas.Label(key=issue['key'], label=label))

                await crud.upsert_issue(schemas.IssueCreate(
                    assignee=(issue['fields']['assignee']
                              or {}).get('displayName'),
                    description=issue['renderedFields']['description'],
                    key=issue['key'],
                    priority=issue['fields']['priority']['name'],
                    status=issue['fields']['status']['name'],
                    summary=issue['fields']['summary']))

            if issues['total'] < idx + page_size:
                break

        logger.info('fetch(%s): fetched %d issues in total', variant,
                    issues['total'])
        task = schemas.Task.parse_obj({
            'key': 'fetch',
            'variant': variant,
            'latest': datetime.datetime.now(datetime.timezone.utc)})
        await crud.upsert_task(task)


async def fetch_closed(client: jira.JIRA) -> None:
    await fetch(
        client,
        interval=datetime.timedelta(minutes=15),
        jql=f"project = '{config.JIRA_PROJECT}' AND status = 'Closed'",
        variant='closed',
    )


async def fetch_open(client: jira.JIRA) -> None:
    await fetch(
        client,
        interval=datetime.timedelta(minutes=5),
        jql=f"project = '{config.JIRA_PROJECT}' AND status != 'Closed'",
        variant='open',
    )
