import contextlib
import datetime
import pathlib
import types
import unittest.mock
from collections.abc import AsyncIterator
from collections.abc import Awaitable
from collections.abc import Callable
from typing import Any
from typing import cast

import fastapi
import httpx
import jira
import pytest
import sqlalchemy.ext.asyncio
import sqlalchemy.orm

import mosura.app
from mosura import database
from mosura import models
from mosura import schemas


class SyncSessionAdapter:
    def __init__(self, db_session: sqlalchemy.orm.Session) -> None:
        self._db_session = db_session

    async def execute(self, statement: Any) -> Any:
        return self._db_session.execute(statement)

    async def commit(self) -> None:
        self._db_session.commit()


@pytest.fixture(scope='function')
async def client() -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=mosura.app.app),
        base_url='http://test',
    ) as c:
        yield c


@pytest.fixture(scope='function')
def jira_raw_factory() -> Callable[..., dict[str, Any]]:
    def _build(  # pylint: disable=too-many-arguments
        *,
        key: str = 'MOS-123',
        status: str = 'In Progress',
        summary: str = 'Ship schema tests',
        description: str = '<p>Rendered description</p>',
        calendar_start: str | None = '2026-01-05',
        issue_start: str | None = None,
        due_date: str | None = '2026-01-19',
        time_original_estimate: str = '0',
        assignee: str | None = 'Test User',
        priority: str = 'High',
        votes: int = 7,
        components: list[str] | None = None,
        labels: list[str] | None = None,
    ) -> dict[str, Any]:
        return {
            'key': key,
            'fields': {
                'assignee': (
                    {'displayName': assignee}
                    if assignee is not None
                    else None
                ),
                'components': [
                    {'name': component}
                    for component in components or []
                ],
                'customfield_12133': calendar_start,
                'customfield_12161': issue_start,
                'duedate': due_date,
                'labels': labels or [],
                'priority': {'name': priority},
                'status': {'name': status},
                'summary': summary,
                'timeoriginalestimate': time_original_estimate,
                'votes': {'votes': votes},
            },
            'renderedFields': {
                'description': description,
            },
        }

    return _build


@pytest.fixture(scope='function')
def jira_issue_factory() -> Callable[[dict[str, Any]], jira.Issue]:
    def _build(raw: dict[str, Any]) -> jira.Issue:
        issue = jira.Issue.__new__(jira.Issue)
        issue.raw = raw
        return issue

    return _build


@pytest.fixture(scope='function')
def issue_factory() -> Callable[..., schemas.Issue]:
    def _build(  # pylint: disable=too-many-arguments
        key: str,
        *,
        summary: str | None = None,
        description: str | None = 'Issue body',
        status: str = 'In Progress',
        assignee: str | None = 'Alice',
        priority: schemas.Priority = schemas.Priority.medium,
        startdate: datetime.date | None = datetime.date(2024, 1, 1),
        timeestimate: datetime.timedelta = datetime.timedelta(days=7),
        votes: int = 0,
        components: list[str] | None = None,
        labels: list[str] | None = None,
    ) -> schemas.Issue:
        return schemas.Issue(
            key=key,
            summary=summary or key,
            description=description,
            status=status,
            assignee=assignee,
            priority=priority,
            startdate=startdate,
            timeestimate=timeestimate,
            votes=votes,
            components=[
                schemas.Component(key=key, component=component)
                for component in components or []
            ],
            labels=[
                schemas.Label(key=key, label=label)
                for label in labels or []
            ],
        )

    return _build


@pytest.fixture(scope='function')
def issue_from_jira_factory() -> Callable[..., schemas.Issue]:
    def _build(
        raw: dict[str, Any],
        *,
        summary: str | None = None,
        components: list[str] | None = None,
        labels: list[str] | None = None,
    ) -> schemas.Issue:
        issue_data = schemas.IssueCreate.from_jira(raw).model_dump()
        if summary is not None:
            issue_data['summary'] = summary

        key = cast(str, issue_data['key'])
        return schemas.Issue(
            **issue_data,
            components=[
                schemas.Component(key=key, component=component)
                for component in components or []
            ],
            labels=[
                schemas.Label(key=key, label=label)
                for label in labels or []
            ],
        )

    return _build


@pytest.fixture(scope='function')
def issue_create_factory() -> Callable[..., schemas.IssueCreate]:
    def _build(
        key: str,
        *,
        summary: str | None = None,
        description: str | None = 'desc',
        status: str,
        assignee: str | None,
        priority: schemas.Priority = schemas.Priority.medium,
        startdate: datetime.date | None = datetime.date(2026, 1, 1),
        timeestimate: datetime.timedelta = datetime.timedelta(days=2),
        votes: int = 1,
    ) -> schemas.IssueCreate:
        return schemas.IssueCreate(
            key=key,
            summary=summary or f'Summary {key}',
            description=description,
            status=status,
            assignee=assignee,
            priority=priority,
            startdate=startdate,
            timeestimate=timeestimate,
            votes=votes,
        )

    return _build


@pytest.fixture(scope='function', name='db_session')
async def fixture_db_session(
    tmp_path: pathlib.Path,
) -> AsyncIterator[sqlalchemy.ext.asyncio.AsyncSession]:
    db = tmp_path / 'models-test.db'
    engine = sqlalchemy.create_engine(f'sqlite:///{db}')
    models.Base.metadata.create_all(engine)

    factory = sqlalchemy.orm.sessionmaker(bind=engine)
    with factory() as db_session:
        adapter = cast(
            sqlalchemy.ext.asyncio.AsyncSession,
            SyncSessionAdapter(db_session),
        )
        yield adapter

    engine.dispose()


@pytest.fixture(scope='function')
def seed_issue(
    db_session: sqlalchemy.ext.asyncio.AsyncSession,
) -> Callable[..., Awaitable[None]]:
    async def _seed(
        issue: schemas.IssueCreate,
        *,
        components: list[str] | None = None,
        labels: list[str] | None = None,
    ) -> None:
        await models.Issue.upsert(issue, session=db_session)
        for component in components or []:
            await models.Component.upsert(
                schemas.Component(key=issue.key, component=component),
                session=db_session,
            )
        for label in labels or []:
            await models.Label.upsert(
                schemas.Label(key=issue.key, label=label),
                session=db_session,
            )

    return _seed


@pytest.fixture(scope='function')
def issue_rows_fetcher(
    db_session: sqlalchemy.ext.asyncio.AsyncSession,
) -> Callable[..., Awaitable[list[models.IssueRow]]]:
    async def _fetch(*, key: str | None = None) -> list[models.IssueRow]:
        query = (
            sqlalchemy.select(
                models.Issue.__table__,
                models.Component.component,
                models.Label.label,
            )
            .join(
                models.Component.__table__,
                models.Issue.key == models.Component.key,
                isouter=True,
            )
            .join(
                models.Label,
                models.Issue.key == models.Label.key,
                isouter=True,
            )
            .order_by(
                models.Issue.key,
                models.Component.component,
                models.Label.label,
            )
        )
        if key:
            query = query.where(models.Issue.key == key)

        rows = await db_session.execute(query)
        return cast(list[models.IssueRow], rows.all())

    return _fetch


@pytest.fixture(scope='function')
def api_session(monkeypatch: pytest.MonkeyPatch) -> types.SimpleNamespace:
    session = types.SimpleNamespace(commit=unittest.mock.AsyncMock())

    @contextlib.asynccontextmanager
    async def fake_session_from_app(
        _app: fastapi.FastAPI,
    ) -> AsyncIterator[types.SimpleNamespace]:
        yield session

    async def run_inline(
        func: Callable[..., Any],
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        return func(*args, **kwargs)

    monkeypatch.setattr(
        database,
        'session_from_app',
        fake_session_from_app,
    )
    monkeypatch.setattr('mosura.api.asyncio.to_thread', run_inline)
    return session


@pytest.fixture(scope='function')
def app_factory() -> Callable[..., fastapi.FastAPI]:
    def _build(
        *,
        projects: list[str],
        open_interval: int = 45,
        closed_interval: int = 3600,
        project_side_effect: Callable[[str], object] | None = None,
    ) -> fastapi.FastAPI:
        app = fastapi.FastAPI()
        app.state.settings = types.SimpleNamespace(
            jira_projects=projects,
            mosura_poll_interval_open=open_interval,
            mosura_poll_interval_closed=closed_interval,
        )
        app.state.jira_client = types.SimpleNamespace(
            project=unittest.mock.Mock(side_effect=project_side_effect),
        )
        return app

    return _build
