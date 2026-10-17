from __future__ import annotations

import datetime
from typing import Annotated

import sqlalchemy
import sqlalchemy.dialects.sqlite
import sqlalchemy.ext.asyncio
import sqlalchemy.orm

from . import schemas
from . import sqltypes

strpk = Annotated[str, sqlalchemy.orm.mapped_column(primary_key=True)]
strpkindex = Annotated[
    str, sqlalchemy.orm.mapped_column(primary_key=True, index=True)
]
strfk = Annotated[
    str,
    sqlalchemy.orm.mapped_column(
        sqlalchemy.ForeignKey('issues.key'), primary_key=True
    ),
]


class Base(
    sqlalchemy.ext.asyncio.AsyncAttrs,
    sqlalchemy.orm.DeclarativeBase,
    sqlalchemy.orm.MappedAsDataclass,
):
    type_annotation_map = {
        datetime.date: sqltypes.DateAsDateTime(),
        datetime.datetime: sqltypes.UTCDateTime(),
    }


class Component(Base):
    __tablename__ = 'components'

    key: sqlalchemy.orm.Mapped[strfk]
    component: sqlalchemy.orm.Mapped[strpk]

    @classmethod
    async def list_(
        cls, key: str, *, session: sqlalchemy.ext.asyncio.AsyncSession
    ) -> set[str]:
        query = sqlalchemy.select(cls.component).where(cls.key == key)
        rows = await session.execute(query)
        return set(rows.scalars())

    @classmethod
    async def delete(
        cls, key: str, *, session: sqlalchemy.ext.asyncio.AsyncSession
    ) -> None:
        query = sqlalchemy.delete(cls).where(cls.key == key)
        await session.execute(query)

    @classmethod
    async def delete_many(
        cls,
        key: str,
        components: set[str],
        *,
        session: sqlalchemy.ext.asyncio.AsyncSession,
    ) -> None:
        if not components:
            return

        query = (
            sqlalchemy.delete(cls)
            .where(cls.key == key)
            .where(cls.component.in_(components))
        )
        await session.execute(query)

    @classmethod
    async def upsert(
        cls,
        component: schemas.Component,
        *,
        session: sqlalchemy.ext.asyncio.AsyncSession,
    ) -> None:
        stmt = sqlalchemy.dialects.sqlite.insert(cls).values(
            **component.model_dump()
        )
        await session.execute(stmt.on_conflict_do_nothing())


class Label(Base):
    __tablename__ = 'labels'

    key: sqlalchemy.orm.Mapped[strfk]
    label: sqlalchemy.orm.Mapped[strpk]

    @classmethod
    async def list_(
        cls, key: str, *, session: sqlalchemy.ext.asyncio.AsyncSession
    ) -> set[str]:
        query = sqlalchemy.select(cls.label).where(cls.key == key)
        rows = await session.execute(query)
        return set(rows.scalars())

    @classmethod
    async def delete(
        cls, key: str, *, session: sqlalchemy.ext.asyncio.AsyncSession
    ) -> None:
        query = sqlalchemy.delete(cls).where(cls.key == key)
        await session.execute(query)

    @classmethod
    async def delete_many(
        cls,
        key: str,
        labels: set[str],
        *,
        session: sqlalchemy.ext.asyncio.AsyncSession,
    ) -> None:
        if not labels:
            return

        query = (
            sqlalchemy.delete(cls)
            .where(cls.key == key)
            .where(cls.label.in_(labels))
        )
        await session.execute(query)

    @classmethod
    async def upsert(
        cls,
        label: schemas.Label,
        *,
        session: sqlalchemy.ext.asyncio.AsyncSession,
    ) -> None:
        stmt = sqlalchemy.dialects.sqlite.insert(cls).values(
            **label.model_dump()
        )
        await session.execute(stmt.on_conflict_do_nothing())


class IssueTransition(Base):
    __tablename__ = 'issue_transitions'

    key: sqlalchemy.orm.Mapped[strfk]
    from_status: sqlalchemy.orm.Mapped[str | None]
    to_status: sqlalchemy.orm.Mapped[str]
    timestamp: sqlalchemy.orm.Mapped[
        Annotated[
            datetime.datetime, sqlalchemy.orm.mapped_column(primary_key=True)
        ]
    ]

    @classmethod
    async def delete(
        cls, key: str, *, session: sqlalchemy.ext.asyncio.AsyncSession
    ) -> None:
        query = sqlalchemy.delete(cls).where(cls.key == key)
        await session.execute(query)

    @classmethod
    async def upsert(
        cls,
        transition: schemas.IssueTransition,
        *,
        session: sqlalchemy.ext.asyncio.AsyncSession,
    ) -> None:
        stmt = sqlalchemy.dialects.sqlite.insert(cls).values(
            **transition.model_dump()
        )
        await session.execute(stmt.on_conflict_do_nothing())

    @classmethod
    async def get_by_keys(
        cls, keys: list[str], *, session: sqlalchemy.ext.asyncio.AsyncSession
    ) -> list[schemas.IssueTransition]:
        query = (
            sqlalchemy.select(cls)
            .where(cls.key.in_(keys))
            .order_by(cls.key, cls.timestamp)
        )
        results = await session.execute(query)
        rows = results.scalars().all()
        return [schemas.IssueTransition.model_validate(row) for row in rows]


class Issue(Base):
    __tablename__ = 'issues'

    key: sqlalchemy.orm.Mapped[strpkindex]
    summary: sqlalchemy.orm.Mapped[str]
    description: sqlalchemy.orm.Mapped[str | None]
    status: sqlalchemy.orm.Mapped[str]
    assignee: sqlalchemy.orm.Mapped[str | None]
    priority: sqlalchemy.orm.Mapped[str]
    startdate: sqlalchemy.orm.Mapped[datetime.date | None]
    created: sqlalchemy.orm.Mapped[datetime.datetime]
    updated: sqlalchemy.orm.Mapped[datetime.datetime]
    timeestimate: sqlalchemy.orm.Mapped[datetime.timedelta]
    votes: sqlalchemy.orm.Mapped[int]

    components: sqlalchemy.orm.Mapped[list[Component]] = (
        sqlalchemy.orm.relationship(order_by=Component.component)
    )
    labels: sqlalchemy.orm.Mapped[list[Label]] = sqlalchemy.orm.relationship(
        order_by=Label.label
    )

    @classmethod
    async def get(
        cls,
        *,
        key: str | None = None,
        assignee: str | None = None,
        closed: bool = False,
        needs_triage: bool = False,
        session: sqlalchemy.ext.asyncio.AsyncSession,
    ) -> list[schemas.Issue]:
        query = sqlalchemy.select(cls).options(
            sqlalchemy.orm.selectinload(cls.components),
            sqlalchemy.orm.selectinload(cls.labels),
        )
        if key:
            query = query.where(cls.key == key)
        if assignee:
            query = query.where(cls.assignee == assignee)
        if not closed:
            query = query.where(cls.status != 'Closed')
        if needs_triage:
            # TODO: make this configurable
            query = query.where(
                sqlalchemy.or_(
                    cls.status == 'Needs Triage',
                    ~cls.components.any(),
                    ~cls.labels.any(),
                )
            )

        rows = (await session.execute(query)).scalars().all()
        return [schemas.Issue.model_validate(row) for row in rows]

    @classmethod
    async def list_keys(
        cls, *, session: sqlalchemy.ext.asyncio.AsyncSession
    ) -> list[str]:
        query = sqlalchemy.select(cls.key).order_by(cls.key)
        rows = await session.execute(query)
        return list(rows.scalars())

    @classmethod
    async def get_updated_map(
        cls, *, session: sqlalchemy.ext.asyncio.AsyncSession
    ) -> dict[str, datetime.datetime]:
        # Change-detection gate: only the stored ``updated`` timestamp is
        # needed, so this deliberately skips the read model and its
        # component/label joins.
        query = sqlalchemy.select(cls.key, cls.updated)
        rows = await session.execute(query)
        return dict(rows.all())

    @classmethod
    async def hard_delete(
        cls, key: str, *, session: sqlalchemy.ext.asyncio.AsyncSession
    ) -> None:
        await Component.delete(key, session=session)
        await Label.delete(key, session=session)
        await IssueTransition.delete(key, session=session)
        query = sqlalchemy.delete(cls).where(cls.key == key)
        await session.execute(query)

    @classmethod
    async def upsert(
        cls,
        issue: schemas.IssueCreate,
        *,
        session: sqlalchemy.ext.asyncio.AsyncSession,
    ) -> None:
        # N.B. set "include" explicitly to support subclasses of IssueCreate
        stmt = sqlalchemy.dialects.sqlite.insert(cls).values(
            **issue.model_dump(
                include=set(schemas.IssueCreate.model_fields.keys())
            )
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

    key: sqlalchemy.orm.Mapped[strpk]
    value: sqlalchemy.orm.Mapped[str]

    @classmethod
    async def get(
        cls, key: str, *, session: sqlalchemy.ext.asyncio.AsyncSession
    ) -> str | None:
        query = sqlalchemy.select(cls.value).where(cls.key == key)
        result = (await session.execute(query)).scalar_one_or_none()
        return result

    @classmethod
    async def upsert(
        cls,
        key: str,
        value: str,
        *,
        session: sqlalchemy.ext.asyncio.AsyncSession,
    ) -> None:
        stmt = sqlalchemy.dialects.sqlite.insert(cls).values(
            key=key, value=value
        )
        query = stmt.on_conflict_do_update(
            index_elements=['key'], set_={'value': stmt.excluded.value}
        )
        await session.execute(query)

    @classmethod
    async def delete(
        cls, key: str, *, session: sqlalchemy.ext.asyncio.AsyncSession
    ) -> None:
        query = sqlalchemy.delete(cls).where(cls.key == key)
        await session.execute(query)


class Task(Base):
    __tablename__ = 'tasks'

    key: sqlalchemy.orm.Mapped[strpkindex]
    variant: sqlalchemy.orm.Mapped[strpkindex]
    latest: sqlalchemy.orm.Mapped[datetime.datetime | None]

    @classmethod
    async def upsert(
        cls,
        task: schemas.Task,
        *,
        session: sqlalchemy.ext.asyncio.AsyncSession,
    ) -> None:
        stmt = sqlalchemy.dialects.sqlite.insert(cls).values(
            **task.model_dump()
        )
        query = stmt.on_conflict_do_update(
            index_elements=['key', 'variant'],
            set_={'latest': stmt.excluded.latest},
        )
        await session.execute(query)

    @classmethod
    async def get(
        cls,
        key: str,
        variant: str,
        *,
        session: sqlalchemy.ext.asyncio.AsyncSession,
    ) -> schemas.Task | None:
        query = (
            sqlalchemy.select(cls.__table__)
            .where(cls.key == key)
            .where(cls.variant == variant)
        )
        result = (await session.execute(query)).one_or_none()
        if not result:
            return None

        return schemas.Task.model_validate(result)
