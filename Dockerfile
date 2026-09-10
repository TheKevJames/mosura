# syntax=docker/dockerfile:1


FROM ghcr.io/astral-sh/uv:0.12.9 AS uv


FROM python:3.13.15-slim-bookworm AS base

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

COPY --from=uv /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/usr/local

WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-dev

COPY mosura ./mosura
COPY static ./static
COPY templates ./templates
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev


FROM base AS test
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen
COPY tests ./tests
ENTRYPOINT ["uv", "run", "--no-sync", "pytest"]
CMD ["tests/"]


FROM base AS app
CMD exec uvicorn --host 0.0.0.0 --port $MOSURA_PORT --proxy-headers mosura.app:app
