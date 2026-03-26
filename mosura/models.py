import datetime
import itertools
import operator
from collections.abc import Sequence
from typing import Annotated

from sqlalchemy import ForeignKey
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.engine.row import Row
from sqlalchemy.ext.asyncio import AsyncAttrs
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.orm import Mapped
from sqlalchemy.orm import mapped_column
from sqlalchemy.orm import MappedAsDataclass
from sqlalchemy.orm import relationship
from sqlalchemy.sql import delete
from sqlalchemy.sql import select

from . import schemas


strpk = Annotated[str, mapped_column(primary_key=True)]
strpkindex = Annotated[str, mapped_column(primary_key=True, index=True)]
strfk = Annotated[
    str, mapped_column(
        ForeignKey('issues.key'),
        primary_key=True,
    ),
]


class Base(AsyncAttrs, DeclarativeBase, MappedAsDataclass):
    pass


class Component(Base):
    __tablename__ = 'components'

    key: Mapped[strfk]
    component: Mapped[strpk]

    @classmethod
    async def list_(cls, key: str, *, session: AsyncSession) -> set[str]:
        query = select(cls.component).where(cls.key == key)
        rows = await session.execute(query)
        return set(rows.scalars())

    @classmethod
    async def delete(cls, key: str, *, session: AsyncSession) -> None:
        query = delete(cls).where(cls.key == key)
        await session.execute(query)

    @classmethod
    async def delete_many(
        cls,
        key: str,
        components: set[str],
        *,
        session: AsyncSession,
    ) -> None:
        if not components:
            return

        query = (
            delete(cls)
            .where(cls.key == key)
            .where(cls.component.in_(components))
        )
        await session.execute(query)

    @classmethod
    async def upsert(
        cls, component: schemas.Component, *,
        session: AsyncSession,
    ) -> None:
        stmt = insert(cls).values(**component.model_dump())
        await session.execute(stmt.on_conflict_do_nothing())


class Label(Base):
    __tablename__ = 'labels'

    key: Mapped[strfk]
    label: Mapped[strpk]

    @classmethod
    async def list_(cls, key: str, *, session: AsyncSession) -> set[str]:
        query = select(cls.label).where(cls.key == key)
        rows = await session.execute(query)
        return set(rows.scalars())

    @classmethod
    async def delete(cls, key: str, *, session: AsyncSession) -> None:
        query = delete(cls).where(cls.key == key)
        await session.execute(query)

    @classmethod
    async def delete_many(
        cls,
        key: str,
        labels: set[str],
        *,
        session: AsyncSession,
    ) -> None:
        if not labels:
            return

        query = (
            delete(cls)
            .where(cls.key == key)
            .where(cls.label.in_(labels))
        )
        await session.execute(query)

    @classmethod
    async def upsert(
        cls, label: schemas.Label, *,
        session: AsyncSession,
    ) -> None:
        stmt = insert(cls).values(**label.model_dump())
        await session.execute(stmt.on_conflict_do_nothing())


class IssueTransition(Base):
    __tablename__ = 'issue_transitions'

    key: Mapped[strfk]
    from_status: Mapped[str | None]
    to_status: Mapped[str]
    timestamp: Mapped[
        Annotated[
            datetime.datetime,
            mapped_column(primary_key=True),
        ]
    ]

    @classmethod
    async def delete(cls, key: str, *, session: AsyncSession) -> None:
        query = delete(cls).where(cls.key == key)
        await session.execute(query)

    @classmethod
    async def upsert(
        cls, transition: schemas.IssueTransition, *,
        session: AsyncSession,
    ) -> None:
        stmt = insert(cls).values(**transition.model_dump())
        await session.execute(stmt.on_conflict_do_nothing())

    @classmethod
    async def get_by_keys(
        cls, keys: list[str], *, session: AsyncSession,
    ) -> list[schemas.IssueTransition]:
        query = select(cls).where(
            cls.key.in_(keys),
        ).order_by(
            cls.key,
            cls.timestamp,
        )
        results = await session.execute(query)
        rows = results.scalars().all()
        return [
            schemas.IssueTransition.model_validate(row)
            for row in rows
        ]


IssueRow = Row[
    tuple[
        str, str, str | None, str, str | None, str,
        datetime.datetime | None, datetime.datetime, datetime.datetime,
        datetime.timedelta, int, datetime.datetime | None, str | None,
        str | None,
    ]
]


# TODO: nuke the convert_* methods, see dataclass?
def convert_field_response(
    key: str, results: Sequence[IssueRow], *,
    idx: int, name: str,
) -> list[dict[str, str]]:
    deduped = {x for x in {x[idx] for x in results} if x}
    ordered = sorted(deduped)
    return [{'key': key, name: x} for x in ordered]


def convert_component_response(
        key: str,
        results: Sequence[IssueRow],
) -> list[dict[str, str]]:
    return convert_field_response(key, results, idx=12, name='component')


def convert_label_response(
        key: str,
        results: Sequence[IssueRow],
) -> list[dict[str, str]]:
    return convert_field_response(key, results, idx=13, name='label')


def convert_issue_response(
        results: Sequence[IssueRow],
) -> list[schemas.Issue]:
    xs = []
    for key, group in itertools.groupby(results, operator.attrgetter('key')):
        fields = list(group)
        # TODO: store tzinfo in db
        startdate = (
            fields[0][6].replace(tzinfo=datetime.UTC)
            if fields[0][6] else None
        )
        created = fields[0][7].replace(tzinfo=datetime.UTC)
        updated = fields[0][8].replace(tzinfo=datetime.UTC)
        xs.append(
            schemas.Issue.model_validate({
                'key': key,
                'summary': fields[0][1],
                'description': fields[0][2],
                'status': fields[0][3],
                'assignee': fields[0][4],
                'priority': fields[0][5],
                'startdate': startdate,
                'created': created,
                'updated': updated,
                'timeestimate': fields[0][9],
                'votes': fields[0][10],
                'components': convert_component_response(key, fields),
                'labels': convert_label_response(key, fields),
            }),
        )

    return xs


class Issue(Base):
    __tablename__ = 'issues'

    key: Mapped[strpkindex]
    summary: Mapped[str]
    description: Mapped[str | None]
    status: Mapped[str]
    assignee: Mapped[str | None]
    priority: Mapped[str]
    startdate: Mapped[datetime.datetime | None]
    created: Mapped[datetime.datetime]
    updated: Mapped[datetime.datetime]
    timeestimate: Mapped[datetime.timedelta]
    votes: Mapped[int]
    transitions_synced_at: Mapped[datetime.datetime | None] = mapped_column(
        nullable=True,
    )

    components: Mapped[list[Component]] = relationship()
    labels: Mapped[list[Label]] = relationship()

    @classmethod
    async def get(
        cls, *, key: str | None = None, assignee: str | None = None,
        closed: bool = False, needs_triage: bool = False,
        session: AsyncSession,
    ) -> list[schemas.Issue]:
        query = (
            select(cls.__table__, Component.component, Label.label)
            .join(Component.__table__, cls.key == Component.key, isouter=True)
            .join(Label, cls.key == Label.key, isouter=True)
        )
        if key:
            query = query.where(cls.key == key)
        if assignee:
            query = query.where(cls.assignee == assignee)
        if not closed:
            query = query.where(cls.status != 'Closed')

        results: Sequence[IssueRow] = (await session.execute(query)).all()
        issues = convert_issue_response(results)
        if needs_triage:
            # TODO: make this configurable
            # TODO: merge this into sql query
            issues = [
                iss for iss in issues
                if iss.status == 'Needs Triage'
                or not iss.components
                or not iss.labels
            ]
        return issues

    @classmethod
    async def list_keys(
        cls, *, session: AsyncSession,
    ) -> list[str]:
        query = select(cls.key).order_by(cls.key)
        rows = await session.execute(query)
        return list(rows.scalars())

    @classmethod
    async def hard_delete(
        cls, key: str, *, session: AsyncSession,
    ) -> None:
        # TODO(perf): group these into a single operation?
        await Component.delete(key, session=session)
        await Label.delete(key, session=session)
        await IssueTransition.delete(key, session=session)
        query = delete(cls).where(cls.key == key)
        await session.execute(query)

    @classmethod
    async def upsert(
        cls, issue: schemas.IssueCreate, *,
        session: AsyncSession,
    ) -> None:
        # TODO: fix upserts, then avoid the deletion here
        deletion = delete(cls).where(cls.key == issue.key)
        await session.execute(deletion)

        # N.B. set "include" explicitly to support subclasses of IssueCreate
        stmt = insert(cls).values(
            **issue.model_dump(
                include=set(schemas.IssueCreate.model_fields.keys()),
            ),
        )
        query = stmt.on_conflict_do_update(
            index_elements=['key'],
            set_={
                'assignee': stmt.excluded.assignee,
                'created': stmt.excluded.created,
                'description': stmt.excluded.description,
                'priority': stmt.excluded.priority,
                'status': stmt.excluded.status,
                'summary': stmt.excluded.summary,
                'startdate': stmt.excluded.startdate,
                'timeestimate': stmt.excluded.timeestimate,
                'updated': stmt.excluded.updated,
                'votes': stmt.excluded.votes,
            },
        )
        await session.execute(query)


class Setting(Base):
    __tablename__ = 'settings'

    key: Mapped[strpk]
    value: Mapped[str]

    @classmethod
    async def get(
        cls, key: str, *, session: AsyncSession,
    ) -> str | None:
        query = select(cls.value).where(cls.key == key)
        result = (await session.execute(query)).scalar_one_or_none()
        return result

    @classmethod
    async def upsert(
        cls, key: str, value: str, *, session: AsyncSession,
    ) -> None:
        stmt = insert(cls).values(key=key, value=value)
        query = stmt.on_conflict_do_update(
            index_elements=['key'],
            set_={'value': stmt.excluded.value},
        )
        await session.execute(query)

    @classmethod
    async def delete(
        cls, key: str, *, session: AsyncSession,
    ) -> None:
        query = delete(cls).where(cls.key == key)
        await session.execute(query)


class Task(Base):
    __tablename__ = 'tasks'

    key: Mapped[strpkindex]
    variant: Mapped[strpkindex]
    latest: Mapped[datetime.datetime | None]

    @classmethod
    async def upsert(
        cls, task: schemas.Task, *,
        session: AsyncSession,
    ) -> None:
        stmt = insert(cls).values(**task.model_dump())
        query = stmt.on_conflict_do_update(
            index_elements=['key', 'variant'],
            set_={'latest': stmt.excluded.latest},
        )
        await session.execute(query)

    @classmethod
    async def get(
        cls, key: str, variant: str, *,
        session: AsyncSession,
    ) -> schemas.Task | None:
        query = (
            select(cls.__table__)
            .where(cls.key == key)
            .where(cls.variant == variant)
        )
        result = (await session.execute(query)).one_or_none()
        if not result:
            return None

        # TODO: any way to store tz in sqlite?
        return schemas.Task.model_validate({
            'key': result.key,
            'variant': result.variant,
            'latest': result.latest.replace(tzinfo=datetime.UTC),
        })
