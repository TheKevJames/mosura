import asyncio
import datetime
import logging
import random
import time
from collections.abc import Iterator
from typing import Any

import fastapi
from sqlalchemy.sql import update

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


def _parse_changelog(
    issue_raw: dict[str, Any],
    key: str,
) -> Iterator[schemas.IssueTransition]:
    """Parse Jira changelog and extract status transitions."""
    histories = issue_raw.get('changelog', {}).get('histories', [])

    for history in histories:
        for item in history.get('items', []):
            if item.get('field') == 'status':
                created_str = history.get('created', '')
                # Parse ISO format from Jira: '2026-01-05T10:00:00.000+0000'
                try:
                    timestamp = datetime.datetime.fromisoformat(
                        created_str.replace('+0000', '+00:00'),
                    ).replace(tzinfo=datetime.UTC)
                except (ValueError, AttributeError):
                    logger.exception(
                        'sync(issue): failed to parse changelog timestamp '
                        'for key=%s with value=%s, skipping',
                        key,
                        created_str,
                    )
                    continue

                from_status = item.get('fromString')
                to_status = item.get('toString', '')

                yield schemas.IssueTransition(
                    key=key,
                    from_status=from_status,
                    to_status=to_status,
                    timestamp=timestamp,
                )


async def _sync_issue_transitions(
    issue: dict[str, Any],
    app: fastapi.FastAPI,
    session: Any,
) -> None:
    """Sync transitions for a single issue from Jira changelog."""
    assignee = (
        issue.get('fields', {}).get('assignee') or {}
    ).get('displayName')
    if assignee != app.state.tracked_user_name:
        # We don't need transitions unless we're rendering timelines, and we
        # only do that for the tracked user.
        return

    existing_issue = await models.Issue.get(
        key=issue['key'],
        closed=True,
        session=session,
    )
    if not existing_issue:
        logger.error(
            'tried to sync transitions for missing issue %s', issue['key'],
        )
        return

    issue_obj = existing_issue[0]
    issue_updated = datetime.datetime.fromisoformat(
        issue['fields']['updated'].replace('+0000', '+00:00'),
    ).replace(tzinfo=datetime.UTC)
    transitions_synced_at = getattr(issue_obj, 'transitions_synced_at', None)
    if transitions_synced_at and transitions_synced_at > issue_updated:
        # Don't sync if the issue hasn't been updated since last time
        return

    try:
        # Fetch full issue with changelog
        full_issue = await asyncio.to_thread(
            app.state.jira_client.issue,
            issue['key'],
            expand='changelog',
        )
        issue_raw = getattr(full_issue, 'raw', {})
        transitions = _parse_changelog(issue_raw, issue['key'])

        # Delete old transitions and insert new ones
        # TODO: switch to upsert, like Component and Label
        await models.IssueTransition.delete(issue['key'], session=session)
        for transition in transitions:
            await models.IssueTransition.upsert(
                transition,
                session=session,
            )

        # Update transitions_synced_at
        # TODO: formalize this into Issue.upsert
        now = datetime.datetime.now(datetime.UTC)
        stmt = update(models.Issue).where(
            models.Issue.key == issue['key'],
        ).values(transitions_synced_at=now)
        await session.execute(stmt)
    except Exception:
        logger.exception(
            'sync(issue): failed to sync transitions for key=%s',
            issue['key'],
        )


async def _upsert_issue_graph(
    issue: dict[str, Any],
    *,
    app: fastapi.FastAPI,
    session: Any,
    sync_transitions: bool = True,
) -> None:
    key = issue['key']

    # upsert Components
    new_components = {
        component['name']
        for component in issue['fields']['components']
    }
    existing_components = await models.Component.list_(key, session=session)
    await models.Component.delete_many(
        key,
        existing_components - new_components,
        session=session,
    )
    for component in sorted(new_components - existing_components):
        await models.Component.upsert(
            schemas.Component(key=key, component=component),
            session=session,
        )

    # upsert Labels
    new_labels = set(issue['fields']['labels'])
    existing_labels = await models.Label.list_(key, session=session)
    await models.Label.delete_many(
        key,
        existing_labels - new_labels,
        session=session,
    )
    for label in sorted(new_labels - existing_labels):
        await models.Label.upsert(
            schemas.Label(key=key, label=label),
            session=session,
        )

    # upsert Issue
    await models.Issue.upsert(
        schemas.IssueCreate.from_jira(issue),
        session=session,
    )

    # Sync transitions for tracked user issues
    if sync_transitions:
        await _sync_issue_transitions(issue, app, session)


async def sync_desired_issues(
    *,
    app: fastapi.FastAPI,
    session: Any,
    transition_timeout: float,
) -> set[str]:
    jql = f'(assignee = "{app.state.tracked_user_id}")'
    custom_jql = await models.Setting.get('custom_jql', session=session)
    if custom_jql:
        jql += f'OR({custom_jql})'

    fetched_issues = await _search_issues(
        jira_client=app.state.jira_client,
        jql=jql,
    )
    logger.debug('sync(desired): fetched=%d', len(fetched_issues))

    deadline = time.monotonic() + max(transition_timeout, 0)
    transitions_enabled = transition_timeout > 0
    transition_syncs = 0
    transition_syncs_skipped = 0

    # If we're timing out regularly, random sampling will at least let us
    # best-effort sync more issue transitions.
    for issue in random.sample(fetched_issues, k=len(fetched_issues)):
        if transitions_enabled and time.monotonic() >= deadline:
            logger.info(
                'sync(desired): transition timeout reached after %d issues',
                transition_syncs,
            )
            transitions_enabled = False

        if transitions_enabled:
            transition_syncs += 1
        else:
            transition_syncs_skipped += 1

        await _upsert_issue_graph(
            issue,
            app=app,
            session=session,
            sync_transitions=transitions_enabled,
        )

    logger.info(
        'sync(desired): upserted=%d transmission_syncs=%d '
        'transition_syncs_skipped=%d',
        len(fetched_issues),
        transition_syncs,
        transition_syncs_skipped,
    )
    return {issue['key'] for issue in fetched_issues}


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
        await _upsert_issue_graph(
            fetched_issue,
            app=app,
            session=session,
        )
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
    session: Any,
    desired_keys: set[str],
) -> set[str]:
    tracked_keys = set(await models.Issue.list_keys(session=session))
    stale_keys = sorted(tracked_keys - desired_keys)
    if not stale_keys:
        return set()

    for key in stale_keys:
        await models.Issue.hard_delete(key, session=session)

    logger.info(
        'sync(stale): pruned %d issues',
        len(stale_keys),
    )
    return set(stale_keys)


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
        async with database.session_from_app(app) as session:
            now = datetime.datetime.now(datetime.UTC)
            task = await models.Task.get('fetch', variant, session=session)

        sleep = _next_sleep_seconds(task, now=now, interval=interval)
        if sleep is not None:
            logger.debug('fetch(%s): too soon, sleeping %ds', variant, sleep)
            await asyncio.sleep(sleep)

        async with database.session_from_app(app) as session:
            logger.info('fetch(%s): fetching data', variant)
            desired_keys = await sync_desired_issues(
                app=app,
                session=session,
                transition_timeout=interval.total_seconds() // 2,
            )
            pruned_keys = await reconcile_stale_issues(
                session=session,
                desired_keys=desired_keys,
            )
            logger.debug(
                'fetch(%s): desired=%d pruned=%d',
                variant,
                len(desired_keys),
                len(pruned_keys),
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
    return {
        asyncio.create_task(
            fetch_desired(app),
            name='fetch_desired',
        ),
    }
