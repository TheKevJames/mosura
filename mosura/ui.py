import fastapi.templating
import starlette

from . import config
from . import crud
from . import schemas


router = fastapi.APIRouter(tags=['ui'])

templates = fastapi.templating.Jinja2Templates(directory='templates')


@router.get('/issues', response_class=fastapi.responses.HTMLResponse)
async def list_issues(
        request: fastapi.Request,
) -> starlette.templating._TemplateResponse:
    issues = await crud.read_issues()
    meta = schemas.Meta(issues)
    return templates.TemplateResponse(
        'issues.list.html',
        {'request': request, 'config': config, 'issues': issues,
         'meta': meta})


@router.get('/mine', response_class=fastapi.responses.HTMLResponse)
async def list_my_issues(
        request: fastapi.Request,
) -> starlette.templating._TemplateResponse:
    issues = await crud.read_issues_for_user(request.app.state.myself)
    meta = schemas.Meta(issues)
    return templates.TemplateResponse(
        'issues.list.html',
        {'request': request, 'config': config, 'issues': issues,
         'meta': meta})


@router.get('/issues/{key}', response_class=fastapi.responses.HTMLResponse)
async def show_issue(request: fastapi.Request,
                     key: str) -> starlette.templating._TemplateResponse:
    issue = await crud.read_issue(key)
    if not issue:
        raise fastapi.HTTPException(status_code=404)

    return templates.TemplateResponse(
        'issues.show.html',
        {'request': request, 'config': config, 'issue': issue})


@router.get('/settings', response_class=fastapi.responses.HTMLResponse)
async def settings(
        request: fastapi.Request,
) -> starlette.templating._TemplateResponse:
    return templates.TemplateResponse(
        'settings.html',
        {'request': request, 'config': config,
         'myself': request.app.state.myself})


@router.get('/triage', response_class=fastapi.responses.HTMLResponse)
async def list_triagable_issues(
        request: fastapi.Request,
) -> starlette.templating._TemplateResponse:
    issues = await crud.read_issues_needing_triage()
    meta = schemas.Meta(issues)
    return templates.TemplateResponse(
        'issues.list.html',
        {'request': request, 'config': config, 'issues': issues,
         'meta': meta})
