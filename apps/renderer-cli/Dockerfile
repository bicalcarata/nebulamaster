FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim

WORKDIR /app

COPY pyproject.toml /app/pyproject.toml
COPY packages /app/packages
COPY apps /app/apps
COPY examples /app/examples

RUN uv sync --no-dev

ENTRYPOINT ["uv", "run", "nebula"]

