FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml /app/agent/pyproject.toml
COPY src /app/agent/src
COPY README.md /app/agent/README.md

RUN pip install -e '/app/agent[test]'

EXPOSE 8000

ARG AGENT_VERSION=dev
ENV ANALYTICS_DUCKDB_PATH=/app/data/published/duckdb/discogs.duckdb \
    ARTIFACTS_DIR=/app/artifacts \
    AGENT_VERSION=${AGENT_VERSION}

ENTRYPOINT ["sh", "-c", "alembic -c /app/agent/src/discogs_agent/persistence/alembic.ini upgrade head && exec uvicorn discogs_agent.api:app --host 0.0.0.0 --port 8000"]
