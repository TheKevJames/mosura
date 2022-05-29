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


async def fetch(client: jira.JIRA) -> None:
    # TODO: consider longer interval for 'Closed' issues
    interval = datetime.timedelta(minutes=5)
    while True:
        now = datetime.datetime.now(datetime.timezone.utc)
        task = await crud.read_task('fetch', 'open')
        if task and task.latest + interval > now:
            logger.debug('fetch(): too soon, sleeping at least %ds',
                         (task.latest - now + interval).seconds)
            await asyncio.sleep(random.uniform(0, 60))
            continue

        logger.info('fetch(): fetching data')
        jql = f"project = '{config.JIRA_PROJECT}'"
        fields = ['key', 'summary', 'description', 'status', 'assignee',
                  'priority', 'components', 'labels']

        page_size = 100
        for idx in itertools.count(0, page_size):
            issues: dict[str, Any] = cast(dict[str, Any],
                                          await asyncio.to_thread(
                client.search_issues, jql, startAt=idx, maxResults=page_size,
                fields=fields, expand='renderedFields', json_result=True))
            logger.debug('fetch(): fetched %d issues, writing to localdb',
                         len(issues.get('issues', [])))
            for issue in issues.get('issues', []):
                for component in issue['fields']['components']:
                    await crud.create_issue_component(
                        schemas.ComponentCreate(component=component['name']),
                        issue['key'])
                for label in issue['fields']['labels']:
                    await crud.create_issue_label(
                        schemas.LabelCreate(label=label), issue['key'])

                await crud.create_issue(schemas.IssueCreate(
                    assignee=(issue['fields']['assignee']
                              or {}).get('displayName'),
                    description=issue['renderedFields']['description'],
                    key=issue['key'],
                    priority=issue['fields']['priority']['name'],
                    status=issue['fields']['status']['name'],
                    summary=issue['fields']['summary'],
                ))

            if issues['total'] < idx + page_size:
                break

        logger.info('fetch(): fetched %d issues in total', issues['total'])
        task = schemas.Task.parse_obj({
            'key': 'fetch',
            'variant': 'open',
            'latest': datetime.datetime.now(datetime.timezone.utc)})
        await crud.update_task(task)
