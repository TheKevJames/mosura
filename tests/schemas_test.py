import datetime

import pytest

from mosura.schemas import IssueCreate


@pytest.mark.parametrize(
    'original,expected',
    [
        ('136800', datetime.timedelta(days=4, hours=6)),
        ('288000', datetime.timedelta(days=14, hours=0)),
        ('424800', datetime.timedelta(days=18, hours=6)),
        ('427500', datetime.timedelta(days=18, hours=6, minutes=45)),
    ],
)
def test_parse_timeestimate(
    original: str,
    expected: datetime.timedelta,
) -> None:
    x = IssueCreate.parse_timeestimate(original)
    assert x == expected
