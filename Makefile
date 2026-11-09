.PHONY: dev lint test smoke migrate eval format check check-image gate quality web seed

# `check` runs lint + tests
# for real, inside Docker, because this host has no .venv and system python has
# ruff/pytest but NOT the app dependencies — `pytest` on the host fails at import
# with ModuleNotFoundError: groundwork.
#
# The bare `lint` / `test` targets below stay host-local on purpose: they are what
# CI runs on a runner that DOES have the deps installed. Do not point `check` at
# them again on this host.
CHECK_IMAGE ?= seismograph-check
CHECK_MOUNT ?= $(CURDIR)

# MSYS_NO_PATHCONV=1: under Git Bash, MSYS rewrites container-side paths as if they
# were host paths — `-w /srv` arrives at the daemon as `C:/Program Files/Git/srv`.
# It is a no-op on Linux/macOS shells.
check: check-image
	MSYS_NO_PATHCONV=1 docker run --rm -v "$(CHECK_MOUNT):/srv" -w /srv -e PYTHONPATH=/srv $(CHECK_IMAGE)

check-image:
	docker build -f Dockerfile.test -t $(CHECK_IMAGE) .

# The one-command gate: lint, tests, route auth, front page, live smoke, eval.
gate:
	python scripts/gate.py

dev:
	uvicorn app.main:app --reload --host $(API_HOST) --port $(API_PORT)

lint:
	ruff check .

test:
	pytest

smoke:
	python scripts/smoke_test.py

migrate:
	alembic upgrade head
	python scripts/check_migrations.py

eval:
	python scripts/eval.py

format:
	ruff format .

# The measured quality gate: nine components, every one at or above 96, or exit 1.
# Needs `pip install -e ".[dev]"` and `npm ci` in web/. Writes quality_report.md.
quality:
	python scripts/quality.py

# Build the dashboard. FastAPI serves web/out when WEB_DIR points at it.
web:
	cd web && npm ci && npm run build

# Record the guide's walkthrough on a running development instance (simulators only).
seed:
	python scripts/seed_demo.py
