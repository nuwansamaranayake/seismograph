# syntax=docker/dockerfile:1
# Stage 1: the dashboard, built once and shipped as static files. No node in production:
# one less process on a host shared with other products.
FROM node:22-alpine AS webbuild
WORKDIR /build/web
COPY web/package.json web/package-lock.json web/.npmrc ./
RUN npm ci --no-audit --no-fund
COPY web/ ./
# scripts/published.mjs reads the published limits from these two files at build time.
COPY EVAL.md eval_report.md /build/
RUN npm run build

FROM python:3.12-slim

WORKDIR /srv
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
# Standard 4 cannot be skipped silently: a bare `docker run` without a dotenv still asserts
# the expected table count (11 app tables + alembic_version). Override via env if the schema
# legitimately changes.
ENV EXPECTED_TABLE_COUNT=12

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

# Build-time facts for the root page. Baked from build args so the deployed page can state
# what is actually running; absent values render as "unknown", never as a placeholder.
ARG APP_VERSION=unreleased
ARG GIT_SHA=unknown
ARG BUILD_TIME=unknown
ENV APP_VERSION=$APP_VERSION GIT_SHA=$GIT_SHA BUILD_TIME=$BUILD_TIME

# The dashboard. app.main mounts it as the front door when WEB_DIR holds a build.
COPY --from=webbuild /build/web/out /srv/web
ENV WEB_DIR=/srv/web

EXPOSE 8000
# Migrate, assert the expected table count (Standard 4), then serve. A container that
# starts serving over an unmigrated schema is exactly the GoviHub failure mode.
CMD ["sh", "-c", "alembic upgrade head && python scripts/check_migrations.py && exec uvicorn app.main:app --host 0.0.0.0 --port 8000"]
