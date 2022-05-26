from collections.abc import AsyncIterator

import httpx
import pytest

from mosura.app import app


@pytest.fixture(scope='function')
async def client() -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient(app=app, base_url='http://test') as c:
        yield c
