# syntax=docker/dockerfile:1

# renovate: datasource=repology depName=debian_11/curl versioning=loose
ARG CURL_VERSION=7.74.0-1.3+deb11u14
# renovate: datasource=pypi depName=poetry
ARG POETRY_VERSION=2.1.3


FROM python:3.13.3-slim-bullseye AS base

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

ARG CURL_VERSION
ARG POETRY_VERSION
RUN --mount=type=cache,target=/var/cache/apt \
    --mount=type=cache,target=/var/lib/apt \
    apt-get update -qy && \
    apt-get install -qy --no-install-recommends \
        "curl=${CURL_VERSION}" && \
    curl -sSL https://install.python-poetry.org | POETRY_VERSION="${POETRY_VERSION}" python3 -
ENV PATH="/root/.local/bin:${PATH}"

RUN poetry config virtualenvs.create false

WORKDIR /app
COPY pyproject.toml poetry.lock ./
RUN --mount=type=cache,target=/root/.cache \
    poetry install --no-root --only main

COPY mosura ./mosura
COPY static ./static
COPY templates ./templates


FROM base AS test
COPY tests ./tests
ENTRYPOINT ["poetry", "run", "pytest"]
CMD ["tests/"]


FROM base AS app
CMD exec uvicorn --host 0.0.0.0 --port $MOSURA_PORT --proxy-headers mosura.app:app
