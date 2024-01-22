import datetime

import pytest

from mosura.schemas import IssueCreate
from mosura.schemas import Priority


@pytest.mark.parametrize(
    'original,expected',
    [
        ('136800', datetime.timedelta(days=4, hours=6)),
        ('288000', datetime.timedelta(days=14, hours=0)),
        ('424800', datetime.timedelta(days=18, hours=6)),
        ('427500', datetime.timedelta(days=18, hours=6, minutes=45)),
    ],
)
def test_issue_timeestimate(
    original: str,
    expected: datetime.timedelta,
) -> None:
    x = IssueCreate(
        key='x', summary='x', status='x', priority=Priority.low,
        timeoriginalestimate=original, description=None,
        assignee=None, startdate=None, votes=0,
    )
    assert x.timeestimate == expected
