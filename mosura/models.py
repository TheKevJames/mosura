import sqlalchemy

from . import database


class Component(database.Base):  # type: ignore
    __tablename__ = 'components'

    key = sqlalchemy.Column(sqlalchemy.String,
                            sqlalchemy.ForeignKey('issues.key'),
                            primary_key=True)
    component = sqlalchemy.Column(sqlalchemy.String, primary_key=True)


class Label(database.Base):  # type: ignore
    __tablename__ = 'labels'

    key = sqlalchemy.Column(sqlalchemy.String,
                            sqlalchemy.ForeignKey('issues.key'),
                            primary_key=True)
    label = sqlalchemy.Column(sqlalchemy.String, primary_key=True)


class Issue(database.Base):  # type: ignore
    __tablename__ = 'issues'

    key = sqlalchemy.Column(sqlalchemy.String, primary_key=True, index=True)
    summary = sqlalchemy.Column(sqlalchemy.String, nullable=False)
    description = sqlalchemy.Column(sqlalchemy.String)
    status = sqlalchemy.Column(sqlalchemy.String, nullable=False)
    assignee = sqlalchemy.Column(sqlalchemy.String)
    priority = sqlalchemy.Column(sqlalchemy.String, nullable=False)

    components: list[Component] = sqlalchemy.orm.relationship(  # type: ignore
        'Component')
    labels: list[Label] = sqlalchemy.orm.relationship('Label')  # type: ignore


class Task(database.Base):  # type:ignore
    __tablename__ = 'tasks'

    key = sqlalchemy.Column(sqlalchemy.String, primary_key=True, index=True)
    latest = sqlalchemy.Column(sqlalchemy.DateTime, nullable=True)
