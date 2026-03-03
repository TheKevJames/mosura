import asyncio
import datetime
import logging
import time
from typing import Any

import fastapi

from . import database
from . import models
from . import schemas


logger = logging.getLogger(__name__)


async def _search_issues(
    *,
    jira_client: Any,
    jql: str,
    page_size: int = 100,
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    page_token: str | None = None

    while True:
        response: dict[str, Any] = await asyncio.to_thread(
            jira_client.enhanced_search_issues,
            jql,
            nextPageToken=page_token,
            maxResults=page_size,
            fields=schemas.Issue.jira_fields(),
            expand='renderedFields',
            json_result=True,
        )
        page: list[dict[str, Any]] = response.get('issues', [])
        issues.extend(page)

        if len(page) < page_size or response.get('isLast') is True:
            break
        page_token = response.get('nextPageToken')

    return issues


def desired_issue_queries(
    app: fastapi.FastAPI,
    *,
    custom_jql: str | None,
) -> list[tuple[str, str]]:
    tracked_user_id = app.state.tracked_user_id
    queries = [('assignee', f'assignee = "{tracked_user_id}"')]

    if custom_jql:
        queries.append(('custom', custom_jql))

    return queries


async def _upsert_issue_graph(
    issue: dict[str, Any],
    *,
    session: Any,
) -> None:
    # TODO: in-place component and label upserts
    await models.Component.delete(issue['key'], session=session)
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


async def sync_desired_issues(
    *,
    app: fastapi.FastAPI,
    session: Any,
) -> set[str]:
    jira_client = app.state.jira_client
    desired_issues: dict[str, dict[str, Any]] = {}

    custom_jql = await models.Setting.get('custom_jql', session=session)
    for variant, jql in desired_issue_queries(app, custom_jql=custom_jql):
        issues = await _search_issues(jira_client=jira_client, jql=jql)
        logger.debug('sync(desired/%s): fetched=%d', variant, len(issues))
        for issue in issues:
            desired_issues[issue['key']] = issue

    for issue in desired_issues.values():
        await _upsert_issue_graph(issue, session=session)

    desired_keys = set(desired_issues)
    logger.info('sync(desired/%s): upserted=%d', variant, len(desired_keys))
    return desired_keys


async def _fetch_issue_by_key(
    *,
    jira_client: Any,
    key: str,
) -> dict[str, Any] | None:
    try:
        issue: object = await asyncio.to_thread(
            jira_client.issue,
            id=key,
            fields=schemas.Issue.jira_fields(),
            expand='renderedFields',
        )
    except Exception:
        logger.info(
            'sync(fetch): fetch failed key=%s, deleting local rows',
            key,
            exc_info=True,
        )
        return None

    raw_issue: object = getattr(issue, 'raw', issue)
    if not isinstance(raw_issue, dict):
        logger.warning(
            'sync(fetch): unexpected final fetch payload for key=%s (type=%s)',
            key,
            type(raw_issue).__name__,
        )
        return None

    typed_issue: dict[str, Any] = raw_issue
    return typed_issue


def _log_issue_refresh_exception(task: asyncio.Task[None]) -> None:
    if task.cancelled():
        return

    exc = task.exception()
    if exc is not None:
        logger.error('sync(issue): background refresh failed', exc_info=exc)


async def refresh_issue_by_key(
    *,
    app: fastapi.FastAPI,
    key: str,
) -> None:
    logger.info('sync(issue): syncing outdated key=%s', key)
    fetched_issue = await _fetch_issue_by_key(
        jira_client=app.state.jira_client,
        key=key,
    )
    if fetched_issue is None:
        logger.warning('sync(issue): unable to refresh key=%s', key)
        return

    async with database.session_from_app(app) as session:
        await _upsert_issue_graph(fetched_issue, session=session)
        await session.commit()


def schedule_issue_refresh(
    *,
    app: fastapi.FastAPI,
    key: str,
) -> None:
    task = asyncio.create_task(
        refresh_issue_by_key(app=app, key=key),
        name=f'refresh_issue_by_key_{key}',
    )
    task.add_done_callback(_log_issue_refresh_exception)


async def reconcile_stale_issues(
    *,
    app: fastapi.FastAPI,
    session: Any,
    desired_keys: set[str],
    timeout_seconds: int,
) -> set[str]:
    tracked_keys = set(await models.Issue.list_keys(session=session))
    stale_keys = sorted(tracked_keys - desired_keys)
    pruned_keys: set[str] = set()
    if not stale_keys:
        return pruned_keys

    deadline = time.monotonic() + max(timeout_seconds, 0)

    for key in stale_keys:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            logger.info(
                'sync(stale): timeout reached after pruning %d/%d issues',
                len(pruned_keys),
                len(stale_keys),
            )
            break

        try:
            final_issue = await asyncio.wait_for(
                _fetch_issue_by_key(
                    jira_client=app.state.jira_client,
                    key=key,
                ),
                timeout=remaining,
            )
        except TimeoutError:
            logger.info(
                'sync(stale): timeout while fetching key=%s, stopping early',
                key,
            )
            break

        if final_issue is not None:
            await _upsert_issue_graph(final_issue, session=session)

        await models.Issue.hard_delete(key, session=session)
        pruned_keys.add(key)

    logger.info(
        'sync(stale): pruned %d/%d issues',
        len(pruned_keys),
        len(stale_keys),
    )
    return pruned_keys


def _next_sleep_seconds(
    task: schemas.Task | None,
    *,
    now: datetime.datetime,
    interval: datetime.timedelta,
) -> int | None:
    if not task or not task.latest:
        return None

    next_run = task.latest + interval
    if next_run <= now:
        return None

    # add a second to avoid race conditions on idle instances
    return int((next_run - now).total_seconds()) + 1


async def fetch_desired(
    app: fastapi.FastAPI,
    lock: asyncio.Lock,
) -> None:
    variant = 'desired'
    interval = datetime.timedelta(
        seconds=app.state.settings.mosura_poll_interval,
    )
    logger.info(
        'fetch(%s): initialized with interval %ds',
        variant,
        interval.seconds,
    )

    while True:
        async with lock, database.session_from_app(app) as session:
            now = datetime.datetime.now(datetime.UTC)
            task = await models.Task.get('fetch', variant, session=session)

        sleep = _next_sleep_seconds(task, now=now, interval=interval)
        if sleep is not None:
            logger.debug('fetch(%s): too soon, sleeping %ds', variant, sleep)
            await asyncio.sleep(sleep)
            if app.state.sync_event.is_set():
                app.state.sync_event.clear()
            else:
                continue

        async with lock, database.session_from_app(app) as session:
            logger.info('fetch(%s): fetching data', variant)
            desired_keys = await sync_desired_issues(app=app, session=session)
            reconcile_timeout_seconds = interval.seconds // 2
            pruned_keys = await reconcile_stale_issues(
                app=app,
                session=session,
                desired_keys=desired_keys,
                timeout_seconds=reconcile_timeout_seconds,
            )
            logger.debug(
                'fetch(%s): desired keys=%d pruned stale keys=%d timeout=%ds',
                variant,
                len(desired_keys),
                len(pruned_keys),
                reconcile_timeout_seconds,
            )
            task = schemas.Task.model_validate({
                'key': 'fetch',
                'variant': variant,
                'latest': datetime.datetime.now(datetime.UTC),
            })
            await models.Task.upsert(task, session=session)
            await session.commit()

        await asyncio.sleep(interval.total_seconds())


async def spawn(
    app: fastapi.FastAPI,
) -> set[asyncio.Task[None]]:
    # TODO: shouldn't this be built into sqlalchemy?
    lock = asyncio.Lock()

    return {
        asyncio.create_task(
            fetch_desired(app, lock),
            name='fetch_desired',
        ),
    }
