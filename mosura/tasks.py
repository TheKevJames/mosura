import asyncio
import datetime
import itertools
import logging
import random
import warnings
from typing import Any
from typing import cast

from . import config
from . import crud
from . import schemas


with warnings.catch_warnings():
    # TODO: fixable?
    warnings.simplefilter('ignore', DeprecationWarning)
    import jira


logger = logging.getLogger(__name__)


# TODO: this ain't the right home
def jira_init() -> jira.JIRA:
    auth = (config.settings.jira_auth_user,
            config.settings.jira_auth_token.get_secret_value())
    try:
        client = jira.JIRA(config.settings.jira_domain, basic_auth=auth,
                           max_retries=0, validate=True)
    except Exception:
        logger.exception('failed to connect to jira')
        # TODO: avoid double-logging, retry some failures, etc
        raise

    return client


jira_client = jira_init()


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
        now = datetime.datetime.now(datetime.UTC)
        task = await crud.read_task('fetch', variant)
        if task and task.latest + interval > now:
            logger.debug('fetch(%s): too soon, sleeping at least %ds', variant,
                         (task.latest - now + interval).seconds)
            await asyncio.sleep(random.uniform(0, 60))
            continue

        logger.info('fetch(%s): fetching data', variant)

        for idx in itertools.count(0, page_size):
            issues: dict[str, Any] = cast(
                dict[str, Any],
                await asyncio.to_thread(
                    jira_client.search_issues,
                    jql,
                    startAt=idx,
                    maxResults=page_size,
                    fields=fields,
                    expand='renderedFields',
                    json_result=True,
                ),
            )
            logger.debug('fetch(%s): fetched %d issues, writing to localdb',
                         variant, len(issues.get('issues', [])))
            for issue in issues.get('issues', []):
                # TODO: in-place component and label upserts
                await crud.delete_issue_components(key=issue['key'])
                for component in issue['fields']['components']:
                    await crud.upsert_issue_component(
                        schemas.Component(key=issue['key'],
                                          component=component['name']))

                await crud.delete_issue_labels(key=issue['key'])
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
                    summary=issue['fields']['summary'],
                    startdate=datetime_or_null(
                        issue['fields']['customfield_12161']),
                    timeoriginalestimate=(
                        issue['fields'].get('timeoriginalestimate') or '0'),
                ))

            if issues['total'] < idx + page_size:
                break

        logger.info('fetch(%s): fetched %d issues in total', variant,
                    issues['total'])
        task = schemas.Task.parse_obj({
            'key': 'fetch',
            'variant': variant,
            'latest': datetime.datetime.now(datetime.UTC)})
        await crud.upsert_task(task)


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


async def spawn(project: str) -> None:
    try:
        _ = jira_client.project(project)
    except Exception:
        logger.exception('failed to query project "%s"', project)
        raise

    asyncio.create_task(fetch_closed(project), name='fetch_closed')
    asyncio.create_task(fetch_open(project), name='fetch_open')
