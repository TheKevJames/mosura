import pytest

from mosura import ui


@pytest.mark.parametrize(
    ('status', 'color'),
    [
        ('Backlog', ''),
        ('Closed', 'green'),
        ('Code Review', 'yellow'),
        ('In Progress', 'yellow'),
        ('Needs Triage', 'red'),
        ('Ready for Testing', ''),
    ],
)
def test_statuscolor_filter(status: str, color: str) -> None:
    template = ui.templates.env.from_string('{{ status | statuscolor }}')
    assert template.render(status=status) == color
