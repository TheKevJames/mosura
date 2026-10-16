import datetime

import sqlalchemy

# pylint: disable=abstract-method
# process_literal_param is optional: TypeDecorator falls back to
# process_bind_param when rendering literals.


class UTCDateTime(sqlalchemy.TypeDecorator[datetime.datetime]):
    # SQLite has no tz-aware storage: persist the naive UTC wall clock and
    # re-attach UTC on read.
    impl = sqlalchemy.DateTime
    cache_ok = True

    def process_bind_param(
        self, value: datetime.datetime | None, dialect: sqlalchemy.Dialect
    ) -> datetime.datetime | None:
        if value is None:
            return None
        if value.utcoffset() is None:
            raise TypeError(f'tz-aware datetime required, got {value!r}')
        return value.astimezone(datetime.UTC).replace(tzinfo=None)

    def process_result_value(
        self, value: datetime.datetime | None, dialect: sqlalchemy.Dialect
    ) -> datetime.datetime | None:
        if value is None:
            return None
        return value.replace(tzinfo=datetime.UTC)


class DateAsDateTime(sqlalchemy.TypeDecorator[datetime.date]):
    # Date columns predate this type and were persisted in SQLite's DATETIME
    # format ("YYYY-MM-DD 00:00:00.000000"), which sqlalchemy.Date cannot
    # parse. Keep that on-disk format so existing databases stay readable.
    impl = sqlalchemy.DateTime
    cache_ok = True

    def process_bind_param(
        self, value: datetime.date | None, dialect: sqlalchemy.Dialect
    ) -> datetime.datetime | None:
        if value is None:
            return None
        return datetime.datetime.combine(value, datetime.time.min)

    def process_result_value(
        self, value: datetime.datetime | None, dialect: sqlalchemy.Dialect
    ) -> datetime.date | None:
        if value is None:
            return None
        return value.date()
