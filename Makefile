.PHONY: dev test lint migrate migration

dev:
	uvicorn larimia.main:app --reload --host 0.0.0.0 --port 8000

test:
	pytest -q

lint:
	ruff check src tests

migrate:
	alembic upgrade head

migration:
	alembic revision --autogenerate -m "$(m)"
