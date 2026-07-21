.PHONY: dev lint test smoke migrate eval format

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
