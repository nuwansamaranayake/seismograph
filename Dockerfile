# syntax=docker/dockerfile:1
FROM python:3.12-slim

WORKDIR /srv
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1

# git is required: aignite-groundwork resolves from a git+https URL (see pyproject.toml)
RUN apt-get update && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

# NOTE: aignite-groundwork is a sibling editable dependency in local dev
# (pip install -e ../groundwork). In CI / image builds it resolves from the
# published wheel or a git ref; see .github/workflows/ci.yml.
COPY pyproject.toml README.md ./
RUN pip install --upgrade pip

COPY . .
RUN pip install .

EXPOSE 8000
# Migrate, assert the expected table count (Standard 4), then serve. A container that
# starts serving over an unmigrated schema is exactly the GoviHub failure mode.
CMD ["sh", "-c", "alembic upgrade head && python scripts/check_migrations.py && exec uvicorn app.main:app --host 0.0.0.0 --port 8000"]
