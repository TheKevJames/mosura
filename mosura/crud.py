import datetime
import itertools
import operator

from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.engine.row import Row  # type: ignore
from sqlalchemy.sql import select

from . import database
from . import models
from . import schemas


Components = models.Component.__table__
Issues = models.Issue.__table__
Labels = models.Label.__table__
Tasks = models.Task.__table__


def convert_issue_response(results: list[Row]) -> list[schemas.Issue]:
    xs = []
    for key, group in itertools.groupby(results, operator.attrgetter('key')):
        fields = list(group)
        xs.append(schemas.Issue.parse_obj({
            'key': key,
            'summary': fields[0][1],
            'description': fields[0][2],
            'status': fields[0][3],
            'assignee': fields[0][4],
            'priority': fields[0][5],
            'components': [{'key': key, 'component': x}
                           for x in {x[6] for x in fields}
                           if x],
            'labels': [{'key': key, 'label': x}
                       for x in {x[7] for x in fields}
                       if x],
        }))

    return xs


async def read_issue(key: str) -> schemas.Issue | None:
    query = (
        select(Issues, Components.c.component, Labels.c.label)
        .where(models.Issue.key == key)
        .join(Components, models.Issue.key == models.Component.key,
              isouter=True)
        .join(Labels, models.Issue.key == models.Label.key, isouter=True)
    )
    results = await database.database.fetch_all(query)
    if not results:
        return None

    return convert_issue_response(results)[0]


async def read_issues() -> list[schemas.Issue]:
    query = (
        select(Issues, Components.c.component, Labels.c.label)
        .where(models.Issue.status != 'Closed')
        .join(Components, models.Issue.key == models.Component.key,
              isouter=True)
        .join(Labels, models.Issue.key == models.Label.key, isouter=True)
    )
    results = await database.database.fetch_all(query)
    return convert_issue_response(results)


async def read_issues_needing_triage() -> list[schemas.Issue]:
    results = await read_issues()
    return [r for r in results
            if r.status == 'Needs Triage'
            or not r.components
            or not r.labels]


async def read_issues_for_user(username: str) -> list[schemas.Issue]:
    query = (
        select(Issues, Components.c.component, Labels.c.label)
        .where(models.Issue.status != 'Closed')
        .where(models.Issue.assignee == username)
        .join(Components, models.Issue.key == models.Component.key,
              isouter=True)
        .join(Labels, models.Issue.key == models.Label.key, isouter=True)
    )
    results = await database.database.fetch_all(query)
    return convert_issue_response(results)


async def create_issue(issue: schemas.IssueCreate) -> None:
    stmt = insert(models.Issue.__table__).values(**issue.dict())
    query = stmt.on_conflict_do_update(
        index_elements=['key'],
        set_={
            'assignee': stmt.excluded.assignee,
            'description': stmt.excluded.description,
            'priority': stmt.excluded.priority,
            'status': stmt.excluded.status,
            'summary': stmt.excluded.summary,
        })
    await database.database.execute(query)


async def create_issue_component(component: schemas.ComponentCreate,
                                 key: str) -> None:
    stmt = insert(models.Component.__table__).values(**component.dict(),
                                                     key=key)
    query = stmt.on_conflict_do_nothing()
    await database.database.execute(query)


async def create_issue_label(label: schemas.LabelCreate, key: str) -> None:
    stmt = insert(models.Label.__table__).values(**label.dict(), key=key)
    query = stmt.on_conflict_do_nothing()
    await database.database.execute(query)


async def read_task(key: str) -> datetime.datetime | None:
    query = (
        select(Tasks.c.latest)
        .where(key == models.Task.key)
    )
    result = await database.database.fetch_one(query)
    if not result:
        return None

    # TODO: any way to store tz in sqlite?
    latest: datetime.datetime = result.latest  # type: ignore
    return latest.replace(tzinfo=datetime.timezone.utc)


async def update_task(key: str, latest: datetime.datetime) -> None:
    stmt = insert(models.Task.__table__).values(key=key, latest=latest)
    query = stmt.on_conflict_do_update(
        index_elements=['key'],
        set_={'latest': stmt.excluded.latest})
    await database.database.execute(query)
