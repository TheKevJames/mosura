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


def convert_issue_response(results: list[Row]) -> list[models.Issue]:
    xs = []
    for key, group in itertools.groupby(results, operator.attrgetter('key')):
        fields = list(group)
        xs.append({
            'key': key,
            'summary': fields[0][1],
            'description': fields[0][2],
            'status': fields[0][3],
            'assignee': fields[0][4],
            'priority': fields[0][5],
            'components': [{'key': key, 'component': x}
                           for x in {x[6] for x in fields}],
            'labels': [{'key': key, 'label': x}
                       for x in {x[7] for x in fields}],
        })

    # TODO: get type hints to work better for sqlalchemy
    return xs  # type: ignore


async def get_issue(key: str) -> models.Issue:
    query = (
        select(Issues, Components.c.component, Labels.c.label)
        .where(key == models.Issue.key)
        .where(models.Issue.key == models.Component.key)
        .where(models.Issue.key == models.Label.key)
    )
    results = await database.database.fetch_all(query)
    return convert_issue_response(results)[0]


async def get_issues(offset: int = 0, limit: int = 100) -> list[models.Issue]:
    query = (
        select(Issues, Components.c.component, Labels.c.label)
        .where(models.Issue.key == models.Component.key)
        .where(models.Issue.key == models.Label.key)
        .offset(offset)
        .limit(limit)
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
