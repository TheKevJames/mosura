import httpx


async def test_root(client: httpx.AsyncClient) -> None:
    response = await client.get('/api/v0/ping')

    assert response.status_code == 200
    assert response.json() == {'status': 'ok'}
