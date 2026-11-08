# The dashboard is static files, so build it on the host's native platform
# (fast even when the final image is cross-built for linux/arm64).
FROM --platform=$BUILDPLATFORM oven/bun:1 AS frontend-build

WORKDIR /app

COPY package.json bun.lock /app/
COPY frontend/package.json /app/frontend/

WORKDIR /app/frontend

RUN bun install

COPY ./frontend /app/frontend

ARG VITE_API_URL=

RUN bun run build


FROM python:3.14

ENV PYTHONUNBUFFERED=1

# lgpio (the Pi GPIO backend, only installed on linux/aarch64) has no wheel for
# this Python version, so it is built from its sdist, which needs SWIG.
# python:3.14 (not -slim) already ships gcc.
RUN apt-get update \
    && apt-get install -y --no-install-recommends swig \
    && rm -rf /var/lib/apt/lists/*

# lgpio writes its notification pipe files to the working directory; keep them
# out of /app/backend.
ENV LG_WD=/tmp

# Install uv
# Ref: https://docs.astral.sh/uv/guides/integration/docker/#installing-uv
# Docker Hub copy of ghcr.io/astral-sh/uv (same release). Docker Desktop on the
# dev Mac can't pull from ghcr.io.
COPY --from=astral/uv:0.9.26 /uv /uvx /bin/

# Compile bytecode
# Ref: https://docs.astral.sh/uv/guides/integration/docker/#compiling-bytecode
ENV UV_COMPILE_BYTECODE=1

# uv Cache
# Ref: https://docs.astral.sh/uv/guides/integration/docker/#caching
ENV UV_LINK_MODE=copy

WORKDIR /app/

# Place executables in the environment at the front of the path
# Ref: https://docs.astral.sh/uv/guides/integration/docker/#using-the-environment
ENV PATH="/app/.venv/bin:$PATH"

# Install dependencies
# Ref: https://docs.astral.sh/uv/guides/integration/docker/#intermediate-layers
# PYPI=1 makes lgpio's setup.py compile its bundled liblgpio sources into the
# extension instead of linking against a system liblgpio (not in Debian).
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    PYPI=1 uv sync --frozen --no-install-workspace --package app

COPY ./backend/scripts /app/backend/scripts

COPY ./backend/pyproject.toml ./backend/alembic.ini /app/backend/

COPY ./backend/app /app/backend/app

COPY --from=frontend-build /app/backend/app/frontend /app/backend/app/frontend

# Sync the project
# Ref: https://docs.astral.sh/uv/guides/integration/docker/#intermediate-layers
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    PYPI=1 uv sync --frozen --package app

WORKDIR /app/backend/

CMD ["fastapi", "run", "--workers", "4"]
