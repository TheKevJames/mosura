import uvicorn


def devserver() -> None:
    uvicorn.run('mosura.app:app', port=8000, reload=True)
