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


def convert_field_response(key: str, results: list[Row], *, idx: int,
                           name: str) -> list[dict[str, str]]:
    deduped = {x for x in {x[idx] for x in results} if x}
    ordered = sorted(deduped)
    return [{'key': key, name: x} for x in ordered]


def convert_component_response(key: str,
                               results: list[Row]) -> list[dict[str, str]]:
    return convert_field_response(key, results, idx=6, name='component')


def convert_label_response(key: str,
                           results: list[Row]) -> list[dict[str, str]]:
    return convert_field_response(key, results, idx=7, name='label')


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
            'components': convert_component_response(key, fields),
            'labels': convert_label_response(key, fields)}))

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


async def upsert_issue(issue: schemas.IssueCreate) -> None:
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


async def upsert_issue_component(component: schemas.Component) -> None:
    stmt = insert(models.Component.__table__).values(**component.dict())
    query = stmt.on_conflict_do_nothing()
    await database.database.execute(query)


async def upsert_issue_label(label: schemas.Label) -> None:
    stmt = insert(models.Label.__table__).values(**label.dict())
    query = stmt.on_conflict_do_nothing()
    await database.database.execute(query)


async def read_task(key: str, variant: str) -> schemas.Task | None:
    query = (
        select(Tasks)
        .where(models.Task.key == key)
        .where(models.Task.variant == variant)
    )
    result = await database.database.fetch_one(query)
    if not result:
        return None

    # TODO: any way to store tz in sqlite?
    return schemas.Task.parse_obj({
        'key': result['key'],
        'variant': result['variant'],
        'latest': result['latest'].replace(tzinfo=datetime.timezone.utc),
    })


async def upsert_task(task: schemas.Task) -> None:
    stmt = insert(models.Task.__table__).values(**task.dict())
    query = stmt.on_conflict_do_update(
        index_elements=['key', 'variant'],
        set_={'latest': stmt.excluded.latest})
    await database.database.execute(query)
