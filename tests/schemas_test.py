import datetime

import pytest

from mosura.schemas import IssueCreate
from mosura.schemas import Quarter


@pytest.mark.parametrize(
    'original,expected',
    [('136800', datetime.timedelta(days=4, hours=6)),
     ('288000', datetime.timedelta(days=14, hours=0)),
     ('424800', datetime.timedelta(days=18, hours=6)),
     ('427500', datetime.timedelta(days=18, hours=6, minutes=45))])
def test_issue_timeestimate(original: str,
                            expected: datetime.timedelta) -> None:
    x = IssueCreate(key='x', summary='x', status='x', priority='x',
                    timeoriginalestimate=original, description=None,
                    assignee=None, startdate=None)
    assert x.timeestimate == expected


@pytest.mark.parametrize(
    'date,expected,display',
    [(datetime.datetime(year=2020, month=1, day=1), (2019, 11), (2019, 4)),
     (datetime.datetime(year=2020, month=2, day=1), (2020, 2), (2020, 1)),
     (datetime.datetime(year=2020, month=3, day=1), (2020, 2), (2020, 1)),
     (datetime.datetime(year=2020, month=4, day=1), (2020, 2), (2020, 1)),
     (datetime.datetime(year=2020, month=5, day=1), (2020, 5), (2020, 2)),
     (datetime.datetime(year=2020, month=6, day=1), (2020, 5), (2020, 2)),
     (datetime.datetime(year=2020, month=7, day=1), (2020, 5), (2020, 2)),
     (datetime.datetime(year=2020, month=8, day=1), (2020, 8), (2020, 3)),
     (datetime.datetime(year=2020, month=9, day=1), (2020, 8), (2020, 3)),
     (datetime.datetime(year=2020, month=10, day=1), (2020, 8), (2020, 3)),
     (datetime.datetime(year=2020, month=11, day=1), (2020, 11), (2020, 4)),
     (datetime.datetime(year=2020, month=12, day=1), (2020, 11), (2020, 4)),
     (datetime.datetime(year=2021, month=1, day=1), (2020, 11), (2020, 4))])
def test_quarter(date: datetime.datetime, expected: tuple[int, int],
                 display: tuple[int, int]) -> None:
    q = Quarter(date)
    assert (q.year, q.startmonth) == expected
    assert q.display == f'{display[0]}Q{display[1]}'
