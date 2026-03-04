# Mosura — Project Context
- This file should be updated in response to any major changes or refactors which affect the following details

## Tech Stack
- **Python 3.11+**, **FastAPI**, **SQLAlchemy** (async, SQLite), **Jinja2** templates
- **Semantic UI** CSS framework, jQuery
- **Poetry** for dependency management (`pyproject.toml` / `poetry.lock`)
- **pydantic-settings** for configuration (`mosura/config.py`)

## Key Files
| File | Purpose |
|---|---|
| `mosura/schemas/` | Pydantic models package; re-exports all schemas from `__init__.py` |
| `mosura/schemas/issue.py` | Issue-related schemas (`Issue`, `IssueCreate`, `IssuePatch`, `IssueTransition`, `Component`, `Label`, `Meta`, `Priority`) |
| `mosura/schemas/task.py` | Task/setting schemas (`Task`, `SettingValue`) |
| `mosura/schemas/timeline.py` | Timeline schemas (`Timeline`, `TimelineIssue`, `TimelineSegment`) |
| `mosura/models.py` | SQLAlchemy ORM models (`Issue`, `Component`, `Label`, `Setting`, `Task`, `IssueTransition`) |
| `mosura/tasks.py` | Background sync with Jira API (`_search_issues`, `_upsert_issue_graph`, `sync_desired_issues`, `fetch_desired`) |
| `mosura/ui.py` | FastAPI routes for HTML pages (`show_timeline`, etc.) |
| `mosura/api.py` | REST API routes |
| `mosura/app.py` | App lifecycle, Jira client setup; DB schema created via `Base.metadata.create_all` (no Alembic) |
| `mosura/config.py` | Settings via pydantic-settings; `config.Jira` subclasses `jira.JIRA` |
| `mosura/database.py` | SQLAlchemy engine/session setup |
| `templates/timeline.html` | Timeline page template |
| `templates/base.html` | Base template (Semantic UI, jQuery) |
| `static/app.css` | Custom CSS |

## Testing
- Tests use **`pytest`** with **`pytest-asyncio`**; `asyncio_mode = "auto"` (set in `pyproject.toml`)
- Fixtures are in `tests/conftest.py`

## Database
- SQLite via async SQLAlchemy
- Schema created via `Base.metadata.create_all` in `app.py` lifespan — **no Alembic migrations**; update models directly
